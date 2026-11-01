import asyncio
import gzip
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import BackgroundTasks, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from redis import Redis
from sqlalchemy import select, text

from apps.api.db import Artifact, CorrectionRecord, Event, Job, ModelExecution, Outbox, StageRun, Video, engine, transaction
from apps.api.orchestration import TERMINAL, emit, schedule
from packages.common.config import settings
from packages.common.storage import Storage
from packages.common.utils import DomainError, file_hash, uid
from packages.schemas.models import Correction, ErrorResponse, JobEvent, LayerOneHandoffManifest, ProcessRequest, SemanticPlan, UploadRequest
from packages.schemas.api import (ArtifactsResponse, HealthResponse, JobDetail, JobView, TrackingReport,
                                  TracksResponse, UploadCompleteResponse, UploadResponse, VideoDetail, VideoListResponse)
from packages.video.processing import probe

app = FastAPI(title="Video-to-Robot-Data · Perception and Interaction", version="0.2.0",
    description="Single-project local API for semantic plans, 2D perception and relative 3D interaction hypotheses; no robot feasibility certification.",
    responses={422: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
app.add_middleware(CORSMiddleware, allow_origins=[settings().web_origin], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(DomainError)
async def domain_error(_, exc):
    return JSONResponse(status_code=exc.status, content=ErrorResponse(code=exc.code, message=exc.message, retryable=exc.retryable).model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_error(_, exc):
    summary = "; ".join(f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors())
    return JSONResponse(status_code=422, content=ErrorResponse(code="E_REQUEST_SCHEMA", message=summary, retryable=False).model_dump())


def video_or_error(s, video_id, lock=False):
    query = select(Video).where(Video.id == video_id)
    video = s.scalar(query.with_for_update() if lock else query)
    if video is None:
        raise DomainError("E_NOT_FOUND", "Video not found", 404)
    return video


def job_or_error(s, job_id):
    job = s.get(Job, job_id)
    if job is None:
        raise DomainError("E_NOT_FOUND", "Job not found", 404)
    return job


def job_view(job):
    return {"job_id": job.id, "video_id": job.video_id, "run_id": job.run_id, "status": job.status,
            "stage": job.stage, "inference_mode": job.mode, "error": job.error,
            "source_job_id": job.source_job_id, "pipeline": job.config.get("pipeline", "perception"),
            "created_at": datetime.fromtimestamp(job.created_at, timezone.utc).isoformat()}


def run_config():
    from workers.pipeline import code_hash
    cfg = settings()
    return {"inference_mode": cfg.inference_mode, "processing_fps": cfg.processing_fps,
            "muse_model": cfg.muse_model, "sam_model": cfg.sam_model, "max_model_calls": cfg.max_model_calls,
            "schema_version": "0.1.0", "code_hash": code_hash()}


def selected_job(s, video_id, run_id):
    video_or_error(s, video_id)
    q = select(Job).where(Job.video_id == video_id)
    if run_id:
        q = q.where(Job.run_id == run_id)
    job = s.scalar(q.order_by(Job.created_at.desc()))
    if job is None:
        raise DomainError("E_RESULT_PENDING", "Video has no selected processing run", 409)
    return job


def artifact_for(video_id, run_id, name):
    with transaction() as s:
        job = selected_job(s, video_id, run_id)
        artifact = s.scalar(select(Artifact).where(Artifact.job_id == job.id, Artifact.name == name))
        if artifact is None:
            raise DomainError("E_RESULT_PENDING", f"{name} is unavailable for this run ({job.status})", 409)
        return artifact


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> dict:
    return {"status": "ok", "inference_mode": settings().inference_mode, "scope": "perception_and_interaction_hypotheses"}


@app.get("/health/ready", response_model=HealthResponse)
def health_ready() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    Redis.from_url(settings().redis_url).ping()
    Storage().client.head_bucket(Bucket=settings().s3_bucket)
    return {"status": "ready", "inference_mode": settings().inference_mode}


@app.get("/v1/videos", response_model=VideoListResponse)
def list_videos() -> dict:
    with transaction() as s:
        rows = s.scalars(select(Video).order_by(Video.id.desc()).limit(100)).all()
        return {"videos": [{"video_id": v.id, "filename": v.filename, "status": v.status} for v in rows]}


@app.post("/v1/videos", status_code=201, response_model=UploadResponse)
def create_video(body: UploadRequest) -> dict:
    if body.byte_count > settings().max_upload_bytes:
        raise DomainError("E_UPLOAD_TOO_LARGE", "Upload exceeds configured byte limit", 413)
    video_id = uid("vid")
    key = f"videos/{video_id}/source/original.mp4"
    with transaction() as s:
        s.add(Video(id=video_id, filename=body.filename, byte_count=body.byte_count, sha256=body.sha256,
                    source_key=key, provenance=body.provenance.model_dump(mode="json")))
    return {"video_id": video_id, "upload_url": Storage().upload_url(key, body.byte_count),
            "upload_headers": {"If-None-Match": "*"}, "expires_in": 900, "inference_mode": settings().inference_mode}


@app.post("/v1/videos/{video_id}/complete-upload", response_model=UploadCompleteResponse)
def complete_upload(video_id: str) -> dict:
    store = Storage()
    with transaction() as s:
        video = video_or_error(s, video_id, True)
        if video.status == "UPLOADED":
            return {"video_id": video.id, "status": video.status}
        try:
            size = store.client.head_object(Bucket=store.bucket, Key=video.source_key)["ContentLength"]
        except Exception as exc:
            raise DomainError("E_UPLOAD_MISSING", "Upload object could not be verified", 409) from exc
        if size != video.byte_count or size > settings().max_upload_bytes:
            raise DomainError("E_UPLOAD_SIZE", "Object size does not match declared upload")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.mp4"
            store.download(video.source_key, path)
            if file_hash(path) != video.sha256:
                raise DomainError("E_UPLOAD_CHECKSUM", "SHA-256 does not match uploaded content")
            metadata = probe(path)
        metadata.pop("source_pts")
        video.probe = metadata
        video.status = "UPLOADED"
        return {"video_id": video.id, "status": video.status, "probe": metadata}


@app.get("/v1/videos/{video_id}", response_model=VideoDetail)
def get_video(video_id: str) -> dict:
    with transaction() as s:
        video = video_or_error(s, video_id)
        jobs = s.scalars(select(Job).where(Job.video_id == video_id).order_by(Job.created_at.desc())).all()
        return {"video_id": video.id, "filename": video.filename, "status": video.status,
                "provenance": video.provenance, "probe": video.probe, "jobs": [job_view(j) for j in jobs],
                "source_url": Storage().url(video.source_key) if video.status == "UPLOADED" else None}


@app.post("/v1/videos/{video_id}/process", status_code=202, response_model=JobView)
def process_video(video_id: str, body: ProcessRequest) -> dict:
    if settings().inference_mode == "live" and not settings().model_api_key:
        raise DomainError("E_CREDENTIALS", "MODEL_API_KEY is required for live mode", 503)
    with transaction() as s:
        video = video_or_error(s, video_id, True)
        if video.status != "UPLOADED":
            raise DomainError("E_UPLOAD_INCOMPLETE", "Complete and validate upload before processing", 409)
        return job_view(schedule(s, video, body.idempotency_key, run_config()))


@app.get("/v1/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str) -> dict:
    with transaction() as s:
        job = job_or_error(s, job_id)
        stages = s.scalars(select(StageRun).where(StageRun.job_id == job_id).order_by(StageRun.attempt)).all()
        models = s.scalars(select(ModelExecution).where(ModelExecution.job_id == job_id)).all()
        return {**job_view(job), "stages": [{"stage": r.stage, "attempt": r.attempt, "status": r.status,
            "error": r.error} for r in stages], "model_runs": [{"model_run_id": r.id, **r.data} for r in models]}


@app.get("/v1/jobs/{job_id}/events")
async def events(job_id: str, request: Request, after: int = Query(0, ge=0), last_event_id: str | None = Header(None)):
    with transaction() as s:
        job_or_error(s, job_id)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise DomainError("E_EVENT_CURSOR", "Last-Event-ID must be an integer") from exc

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            with transaction() as s:
                job = job_or_error(s, job_id)
                rows = s.scalars(select(Event).where(Event.job_id == job_id, Event.sequence > cursor)
                                 .order_by(Event.sequence).limit(100)).all()
                terminal = job.status in TERMINAL
            for row in rows:
                event = JobEvent(sequence=row.sequence, job_id=row.job_id, status=row.status,
                    stage=row.stage, created_at=datetime.fromtimestamp(row.created_at, timezone.utc), detail=row.detail)
                yield f"id: {row.sequence}\ndata: {event.model_dump_json()}\n\n"
                cursor = row.sequence
            if terminal and len(rows) < 100:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/v1/jobs/{job_id}/retry", status_code=202, response_model=JobView)
def retry(job_id: str) -> dict:
    with transaction() as s:
        job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise DomainError("E_NOT_FOUND", "Job not found", 404)
        if job.status != "FAILED":
            raise DomainError("E_RETRY_STATE", "Only failed jobs can be retried", 409)
        if job.error and job.error["code"] == "E_PROVIDER_OUTCOME_UNKNOWN":
            raise DomainError("E_PROVIDER_OUTCOME_UNKNOWN", "Inspect provider request status before creating a new run", 409)
        job.status, job.error, job.lease_token, job.lease_until = "QUEUED", None, None, None
        emit(s, job, {"manual_retry": True})
        s.add(Outbox(job_id=job.id))
        return job_view(job)


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: str) -> dict:
    with transaction() as s:
        job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise DomainError("E_NOT_FOUND", "Job not found", 404)
        if job.status not in TERMINAL:
            job.cancel_requested = True
            job.status = "CANCELLED"
            job.lease_token = job.lease_until = None
            emit(s, job)
        return job_view(job)


@app.get("/v1/videos/{video_id}/actions", response_model=SemanticPlan)
def actions(video_id: str, run_id: str | None = None) -> dict:
    artifact = artifact_for(video_id, run_id, "semantic_plan.json")
    return json.loads(Storage().read(artifact.manifest["uri"]))


@app.get("/v1/videos/{video_id}/tracking-report", response_model=TrackingReport)
def tracking_report(video_id: str, run_id: str | None = None) -> dict:
    return json.loads(Storage().read(artifact_for(video_id, run_id, "tracking_report.json").manifest["uri"]))


@app.get("/v1/videos/{video_id}/handoff", response_model=LayerOneHandoffManifest)
def handoff(video_id: str, run_id: str | None = None) -> dict:
    return json.loads(Storage().read(artifact_for(video_id, run_id, "handoff_manifest.json").manifest["uri"]))


@app.get("/v1/videos/{video_id}/artifacts", response_model=ArtifactsResponse)
def artifacts(video_id: str, run_id: str | None = None) -> dict:
    store = Storage()
    with transaction() as s:
        job = selected_job(s, video_id, run_id)
        rows = s.scalars(select(Artifact).where(Artifact.job_id == job.id)).all()
        return {"run_id": job.run_id, "inference_mode": job.mode, "artifacts": [
            {"name": a.name, **a.manifest, "url": store.url(a.manifest["uri"])} for a in rows]}


@app.get("/v1/videos/{video_id}/tracks", response_model=TracksResponse)
def tracks(video_id: str, run_id: str | None = None, shot_id: str | None = None,
           entity_id: str | None = None, start_s: float = Query(0, ge=0), end_s: float = Query(120, ge=0),
           offset: int = Query(0, ge=0), limit: int = Query(300, ge=1, le=2000), include_masks: bool = False) -> dict:
    if end_s < start_s:
        raise DomainError("E_INTERVAL", "end_s must be >= start_s")
    artifact = artifact_for(video_id, run_id, "tracks.parquet")
    store = Storage()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tracks.parquet"
        store.download(artifact.manifest["uri"], path)
        filters = [("timestamp", ">=", start_s), ("timestamp", "<=", end_s)]
        if shot_id:
            filters.append(("shot_id", "=", shot_id))
        if entity_id:
            filters.append(("entity_id", "=", entity_id))
        all_rows = pq.read_table(path, filters=filters).to_pylist()
    all_rows.sort(key=lambda r: (r["frame_index"], r["track_id"]))
    rows = all_rows[offset:offset + limit]
    masks, bundles = {}, {}
    if include_masks:
        if len(rows) > 200:
            raise DomainError("E_MASK_WINDOW", "Mask decoding windows are limited to 200 rows")
        # Only resolve bundles referenced by this run's selected table.
        for row in rows:
            if row["mask_ref"]:
                key, fragment = row["mask_ref"].split("#", 1)
                if key not in bundles:
                    bundles[key] = json.loads(gzip.decompress(store.read(key)))
                masks[row["mask_ref"]] = bundles[key][fragment]
    return {"total": len(all_rows), "offset": offset, "tracks": rows, "masks": masks}


@app.post("/v1/videos/{video_id}/corrections", status_code=202, response_model=JobView)
def corrections(video_id: str, body: Correction) -> dict:
    with transaction() as s:
        video = video_or_error(s, video_id, True)
        source = job_or_error(s, body.source_job_id)
        if source.video_id != video_id or source.status not in ("COMPLETED", "NEEDS_REVIEW") or source.config.get("pipeline") == "reconstruction":
            raise DomainError("E_CORRECTION_SOURCE", "Correction source must be a completed run of this video", 409)
        if source.mode != settings().inference_mode:
            raise DomainError("E_CORRECTION_MODE", "Select the source run's inference mode before correcting it", 409)
        rows = s.scalars(select(Artifact).where(Artifact.job_id == source.id)).all()
        manifest_row = next((a for a in rows if a.name == "manifest.json"), None)
        semantic_row = next((a for a in rows if a.name == "semantic_plan.json"), None)
        store = Storage()
        manifest = json.loads(store.read(manifest_row.manifest["uri"]))
        plan = json.loads(store.read(semantic_row.manifest["uri"]))
        shot = next((shot for shot in manifest["shots"] if shot["shot_id"] == body.shot_id), None)
        if not shot or not shot["start_frame"] <= body.frame_index < shot["end_frame"] or body.entity_id not in {e["entity_id"] for e in plan["entities"]}:
            raise DomainError("E_CORRECTION_REFERENCE", "Invalid frame, shot, or entity reference")
        coords = [body.point] if body.point else []
        if body.point and not (0 <= body.point[0] < manifest["width"] and 0 <= body.point[1] < manifest["height"]):
            raise DomainError("E_CORRECTION_COORDINATES", "Point must lie inside normalized image pixels")
        if body.bbox_xyxy:
            coords += [body.bbox_xyxy[:2], body.bbox_xyxy[2:]]
        if any(not (0 <= p[0] <= manifest["width"] and 0 <= p[1] <= manifest["height"]) for p in coords):
            raise DomainError("E_CORRECTION_COORDINATES", "Correction outside normalized image")
        job = schedule(s, video, uid("correction"), {**source.config, "code_hash": run_config()["code_hash"]}, source.id)
        s.add(CorrectionRecord(video_id=video_id, job_id=job.id, data=body.model_dump(mode="json")))
        return job_view(job)


@app.get("/v1/demo-source")
def demo_source(background_tasks: BackgroundTasks):
    if settings().inference_mode != "fixture":
        raise DomainError("E_DEMO_MODE", "Synthetic demo is available only in fixture mode", 409)
    from scripts.make_fixtures import make_video
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "synthetic.mp4"
    make_video(path)
    background_tasks.add_task(directory.cleanup)
    return FileResponse(path, media_type="video/mp4", filename="synthetic-fixture.mp4", background=background_tasks)


from apps.api.reconstruction import router as reconstruction_router
app.include_router(reconstruction_router)

import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import APIRouter, Query
from sqlalchemy import select

from apps.api.db import Artifact, Job, transaction
from apps.api.orchestration import schedule
from packages.common.config import settings
from packages.common.storage import Storage
from packages.common.utils import DomainError
from packages.geometry.providers import provider_fingerprint
from packages.schemas.api import JobView
from packages.schemas.reconstruction import (GeometryWindow, LayerTwoHandoff, ReconstructionReport,
    ReconstructionRequest, RefinedAction)

router = APIRouter()


@router.post("/v1/videos/{video_id}/reconstruct", status_code=202, response_model=JobView)
def reconstruct_video(video_id: str, body: ReconstructionRequest):
    from apps.api.main import job_or_error, job_view, run_config, video_or_error
    with transaction() as session:
        video = video_or_error(session, video_id, True)
        source = job_or_error(session, body.source_job_id)
        if source.video_id != video_id or source.status not in ("COMPLETED", "NEEDS_REVIEW") or source.config.get("pipeline") == "reconstruction":
            raise DomainError("E_RECONSTRUCTION_SOURCE", "Select a finished layer-one run of this video", 409)
        key = "phase2:" + body.idempotency_key
        existing = session.scalar(select(Job).where(Job.video_id == video_id, Job.idempotency_key == key))
        if existing:
            original = existing.config["reconstruction"]
            if existing.source_job_id != source.id or any(original.get(k) != v for k, v in body.config.model_dump().items()):
                raise DomainError("E_IDEMPOTENCY_CONFLICT", "This key already selected a different reconstruction configuration", 409)
            return job_view(existing)
        if body.config.backend == "fixture" and source.mode != "fixture":
            raise DomainError("E_GEOMETRY_MODE", "Fixture geometry is permitted only on fixture perception runs", 409)
        artifact = session.scalar(select(Artifact).where(Artifact.job_id == source.id, Artifact.name == "handoff_manifest.json"))
        if artifact is None:
            raise DomainError("E_RECONSTRUCTION_INPUTS", "Layer-one handoff is not available", 409)
        handoff = json.loads(Storage().read(artifact.manifest["uri"]))
        if source.mode == "live" and not handoff["ready_for_geometry"] and not body.allow_review_source:
            raise DomainError("E_REVIEW_REQUIRED", "Resolve layer-one review reasons or explicitly set allow_review_source", 409)
        cfg = settings()
        config = {**body.config.model_dump(), "gpu_python": cfg.geometry_python,
            "vggt_checkpoint": cfg.vggt_checkpoint, "body_checkpoint": cfg.sam3d_body_checkpoint,
            "body_mhr": cfg.sam3d_mhr_path, "timeout": cfg.stage_timeout_seconds}
        config["provider_fingerprint"] = provider_fingerprint(config)
        frozen = {**run_config(), "inference_mode": source.mode, "pipeline": "reconstruction", "reconstruction": config}
        return job_view(schedule(session, video, key, frozen, source.id))


@router.get("/v1/videos/{video_id}/geometry-report", response_model=ReconstructionReport)
def geometry_report(video_id: str, run_id: str | None = None):
    from apps.api.main import artifact_for
    artifact = artifact_for(video_id, run_id, "reconstruction_report.json")
    return json.loads(Storage().read(artifact.manifest["uri"]))


@router.get("/v1/videos/{video_id}/phase2-handoff", response_model=LayerTwoHandoff)
def phase2_handoff(video_id: str, run_id: str | None = None):
    from apps.api.main import artifact_for
    artifact = artifact_for(video_id, run_id, "phase2_handoff.json")
    return json.loads(Storage().read(artifact.manifest["uri"]))


@router.get("/v1/videos/{video_id}/refined-actions", response_model=list[RefinedAction])
def refined_actions(video_id: str, run_id: str | None = None):
    from apps.api.main import artifact_for
    artifact = artifact_for(video_id, run_id, "refined_actions.json")
    return json.loads(Storage().read(artifact.manifest["uri"]))


def window(video_id, run_id, shot_id, entity_id, start_s, end_s, offset, limit, include_points, contacts_only=False):
    from apps.api.main import selected_job
    if end_s < start_s:
        raise DomainError("E_INTERVAL", "end_s must be >= start_s")
    with transaction() as session:
        job = selected_job(session, video_id, run_id)
        artifacts = {a.name: a for a in session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all()}
    names = {"contacts": "contacts.parquet"} if contacts_only else {
        "cameras": "cameras.parquet", "hands": "hand_pose.parquet", "objects": "object_pose.parquet",
        "relative": "object_centric.parquet", "contacts": "contacts.parquet"}
    if not set(names.values()) <= artifacts.keys():
        raise DomainError("E_RESULT_PENDING", "Reconstruction tables are not available for the selected run", 409)
    result = {}
    store = Storage()
    with tempfile.TemporaryDirectory() as tmp:
        for name, filename in names.items():
            path = Path(tmp) / filename
            store.download(artifacts[filename].manifest["uri"], path)
            filters = [("timestamp", ">=", start_s), ("timestamp", "<=", end_s)]
            if shot_id: filters.append(("shot_id", "=", shot_id))
            rows = pq.read_table(path, filters=filters).to_pylist()
            if entity_id and name != "cameras":
                rows = [r for r in rows if entity_id in (r.get("entity_id"), r.get("hand_id"), r.get("object_id"))]
            if not include_points and name in ("hands", "objects"):
                for row in rows: row["points_world"] = []
            result[name] = rows
    frames = sorted({r["frame_index"] for rows in result.values() for r in rows})
    selected = set(frames[offset:offset+limit])
    return {"total": len(frames), "offset": offset,
        **{name: [r for r in rows if r["frame_index"] in selected] for name, rows in result.items()}}


@router.get("/v1/videos/{video_id}/geometry", response_model=GeometryWindow)
def geometry(video_id: str, run_id: str | None = None, shot_id: str | None = None, entity_id: str | None = None,
    start_s: float = Query(0, ge=0, allow_inf_nan=False), end_s: float = Query(120, ge=0, allow_inf_nan=False),
    offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000), include_points: bool = False):
    return window(video_id, run_id, shot_id, entity_id, start_s, end_s, offset, limit, include_points)


@router.get("/v1/videos/{video_id}/contacts", response_model=GeometryWindow)
def contacts(video_id: str, run_id: str | None = None, shot_id: str | None = None, entity_id: str | None = None,
    start_s: float = Query(0, ge=0, allow_inf_nan=False), end_s: float = Query(120, ge=0, allow_inf_nan=False),
    offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000)):
    return window(video_id, run_id, shot_id, entity_id, start_s, end_s, offset, limit, False, contacts_only=True)

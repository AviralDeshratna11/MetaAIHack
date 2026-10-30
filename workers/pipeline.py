import json
import mimetypes
import tempfile
import threading
import time
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import func, select

from apps.api.db import (ActionRecord, Artifact, CorrectionRecord, EntityRecord, Job, ModelExecution,
                         StageRun, Video, transaction)
from apps.api.orchestration import assert_owner, claim, emit, heartbeat
from packages.common.storage import Storage
from packages.common.utils import DomainError, digest, file_hash, now, uid
from packages.meta_client.fixture import FixtureProvider
from packages.meta_client.live import LiveProvider
from packages.schemas.models import ArtifactManifest, LayerOneHandoffManifest, ModelRun, SemanticPlan, VideoManifest
from packages.video.processing import normalize
from workers.perception.tracking import tracking
from workers.semantic.parser import PROMPT, parse_semantics

STAGES = ("preprocessing", "semantic_parsing", "tracking")


def code_hash():
    roots = [Path("packages"), Path("workers"), Path("apps/api")]
    sources = {str(p): file_hash(p) for root in roots for p in sorted(root.rglob("*.py"))}
    sources["requirements.lock"] = file_hash(Path("requirements.lock"))
    return digest(sources)


class Recorder:
    def __init__(self, job, stage, token, store):
        self.job, self.stage, self.token, self.store = job, stage, token, store
        self.mode = job.mode
        self.last_id = ""
        self.active = {}

    def lookup(self, key):
        with transaction() as s:
            records = s.scalars(select(ModelExecution).where(ModelExecution.job_id == self.job.id)).all()
            completed = [r for r in records if r.data["input_hash"] == key and r.data["status"] == "completed"]
            if completed:
                r = completed[-1]
                self.last_id = r.id
                return json.loads(self.store.read(r.data["raw_ref"]))
            if any(r.data["input_hash"] == key and r.data["status"] in ("started", "unknown") for r in records):
                raise DomainError("E_PROVIDER_OUTCOME_UNKNOWN", "Earlier request outcome unknown. Inspect model run before a new submission.", 409)
        return None

    def __call__(self, event):
        key = event.get("request_key", uid("fixture_request"))
        status = event["status"]
        if status == "started":
            with transaction() as s:
                assert_owner(s, self.job.id, self.token)
                count = s.scalar(select(func.count()).select_from(ModelExecution).where(ModelExecution.job_id == self.job.id))
                if count >= self.job.config["max_model_calls"]:
                    raise DomainError("E_MODEL_BUDGET", "Per-job model request budget exhausted")
            self.active[key] = uid("model")
        model_id = self.active.get(key, uid("model"))
        self.last_id = model_id
        data = ModelRun(model_run_id=model_id, model=event["model"], stage=self.stage.stage,
            inference_mode=self.mode, input_hash=key, config_hash=digest(self.job.config),
            prompt_hash=digest(PROMPT if self.stage.stage == "semantic_parsing" else "sam-concepts-v1"),
            status=status, request_id=event.get("request_id"), latency_ms=event.get("latency_ms"),
            usage=event.get("usage", {}), attempt=event.get("attempt", 1), error=event.get("error")).model_dump(mode="json")
        if "raw_output" in event:
            raw = event["raw_output"].encode()
            key_path = f"videos/{self.job.video_id}/runs/{self.job.run_id}/{self.stage.id}/model/{model_id}.json"
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "response.json"
                path.write_bytes(raw)
                self.store.upload(path, key_path, "application/json")
            data["raw_ref"] = key_path
        with transaction() as s:
            assert_owner(s, self.job.id, self.token)
            existing = s.get(ModelExecution, model_id)
            if existing:
                existing.data = data
            else:
                s.add(ModelExecution(id=model_id, job_id=self.job.id, data=data))


def stage_start(job_id, token, stage_name, cache_key):
    with transaction() as s:
        job = assert_owner(s, job_id, token)
        done = s.scalar(select(StageRun).where(StageRun.job_id == job.id, StageRun.stage == stage_name,
                                             StageRun.status == "COMPLETED"))
        if done:
            return done, True
        prior = s.scalars(select(StageRun).where(StageRun.job_id == job.id, StageRun.stage == stage_name)).all()
        if len(prior) >= 3:
            raise DomainError("E_STAGE_RETRIES", "Stage exceeded three total execution attempts")
        for old in prior:
            if old.status == "RUNNING":
                old.status, old.error = "FAILED", {"code": "E_WORKER_INTERRUPTED"}
        cached = s.scalar(select(StageRun).join(Job).where(Job.video_id == job.video_id,
            StageRun.cache_key == cache_key, StageRun.status == "COMPLETED").order_by(StageRun.attempt.desc()))
        stage = StageRun(job_id=job.id, stage=stage_name, attempt=len(prior) + 1, cache_key=cache_key,
                         status="COMPLETED" if cached else "RUNNING", result=cached.result if cached else None)
        s.add(stage)
        s.flush()
        job.status, job.stage = stage_name.upper(), stage_name
        emit(s, job, {"cache_hit": cached is not None, "stage_run_id": stage.id})
        if cached:
            for a in s.scalars(select(Artifact).where(Artifact.stage_run_id == cached.id)).all():
                s.add(Artifact(id=uid("art"), job_id=job.id, stage_run_id=stage.id, name=a.name, manifest=a.manifest))
        return stage, cached is not None


def publish_directory(job, stage, directory, token, store, input_hashes, model=None):
    manifests, refs = [], {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        key = f"videos/{job.video_id}/runs/{job.run_id}/{stage.id}/{stage.stage}/{name}"
        media = "application/gzip" if name.endswith(".gz") else mimetypes.guess_type(name)[0] or "application/octet-stream"
        store.upload(path, key, media)
        manifest = ArtifactManifest(artifact_id=uid("art"), uri=key, sha256=file_hash(path), byte_count=path.stat().st_size,
            media_type=media, stage=stage.stage, run_id=job.run_id, input_hashes=input_hashes,
            config_hash=digest(job.config), code_hash=job.config["code_hash"], model=model,
            prompt_hash=digest(PROMPT) if stage.stage == "semantic_parsing" else None,
            created_at=now(), inference_mode=job.mode)
        manifests.append((name, manifest))
        refs[name] = key
    with transaction() as s:
        assert_owner(s, job.id, token)
        for name, manifest in manifests:
            s.add(Artifact(id=manifest.artifact_id, job_id=job.id, stage_run_id=stage.id,
                           name=name, manifest=manifest.model_dump(mode="json")))
    return refs


def all_corrections(job):
    corrections = []
    with transaction() as s:
        current = job
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            row = s.scalar(select(CorrectionRecord).where(CorrectionRecord.job_id == current.id))
            if row:
                corrections.insert(0, row.data)
            current = s.get(Job, current.source_job_id) if current.source_job_id else None
    # Latest correction of each kind wins, without mutating earlier model output.
    latest = {(c["entity_id"], c["shot_id"], c["kind"]): c for c in corrections}
    return list(latest.values())


def run_job(job_id):
    token = claim(job_id)
    if not token:
        return
    stop = threading.Event()

    def pulse():
        while not stop.wait(20):
            try:
                if not heartbeat(job_id, token):
                    return
            except Exception:
                return

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    stage = None
    try:
        with transaction() as s:
            job = s.get(Job, job_id)
            video = s.get(Video, job.video_id)
        if job.config["code_hash"] != code_hash():
            raise DomainError("E_CODE_CHANGED", "Compiler code changed after submission; create a new processing run to preserve provenance", 409)
        provider = FixtureProvider() if job.mode == "fixture" else LiveProvider(config=job.config)
        store = Storage()
        corrections = all_corrections(job)
        input_key = {"source": video.sha256, "config": job.config}
        results = {}
        for stage_name in STAGES:
            stage_key = digest({**input_key, "stage": stage_name,
                                "corrections": corrections if stage_name == "tracking" else []})
            stage, cache_hit = stage_start(job.id, token, stage_name, stage_key)
            if not cache_hit:
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    output = root / "output"
                    output.mkdir()
                    recorder = Recorder(job, stage, token, store)
                    if stage_name == "preprocessing":
                        source = root / "source.mp4"
                        store.download(video.source_key, source)
                        normalize(source, output, video.id, job.config["processing_fps"])
                    else:
                        normalized = results["preprocessing"]
                        manifest = VideoManifest.model_validate_json(store.read(normalized["manifest.json"]))
                        source = root / "normalized.mp4"
                        store.download(normalized["video_720p_15fps.mp4"], source)
                        if stage_name == "semantic_parsing":
                            plan, raws = parse_semantics(provider, source, manifest.duration_s, recorder)
                            (output / "semantic_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
                            (output / "action_graph.json").write_text(plan.action_graph.model_dump_json(indent=2), encoding="utf-8")
                            (output / "semantic_attempts.json").write_text(json.dumps(raws), encoding="utf-8")
                        else:
                            plan = SemanticPlan.model_validate_json(store.read(results["semantic_parsing"]["semantic_plan.json"]))
                            frame_file = root / "frame_map.parquet"
                            store.download(normalized["frame_map.parquet"], frame_file)
                            prefix = f"videos/{job.video_id}/runs/{job.run_id}/{stage.id}/tracking"
                            tracking(provider, source, manifest, plan, pq.read_table(frame_file).to_pylist(),
                                     output, prefix, recorder, corrections)
                    refs = publish_directory(job, stage, output, token, store, [video.sha256],
                        ("synthetic-semantic-v1" if job.mode == "fixture" else job.config["muse_model"]) if stage_name == "semantic_parsing"
                        else ("synthetic-color-tracker-v1" if job.mode == "fixture" else job.config["sam_model"]) if stage_name == "tracking" else None)
                with transaction() as s:
                    current = assert_owner(s, job.id, token)
                    saved = s.get(StageRun, stage.id)
                    saved.status, saved.result = "COMPLETED", refs
                    emit(s, current, {"stage_completed": stage_name})
                stage.result = refs
            results[stage_name] = stage.result
            if stage_name == "semantic_parsing":
                plan = SemanticPlan.model_validate_json(store.read(stage.result["semantic_plan.json"]))
                with transaction() as s:
                    assert_owner(s, job.id, token)
                    if not s.scalar(select(EntityRecord).where(EntityRecord.job_id == job.id)):
                        for entity in plan.entities:
                            s.add(EntityRecord(job_id=job.id, entity_id=entity.entity_id, data=entity.model_dump(mode="json")))
                        for action in plan.actions:
                            s.add(ActionRecord(job_id=job.id, action_id=action.action_id, data=action.model_dump(mode="json")))
        report = json.loads(store.read(results["tracking"]["tracking_report.json"]))
        reasons = report["review_reasons"] + (["Synthetic fixture output; requires live-model validation"] if job.mode == "fixture" else [])
        reasons += plan.warnings
        refs = {f"{stage_name}/{name}": key for stage_name, artifacts in results.items() for name, key in artifacts.items()}
        handoff = LayerOneHandoffManifest(video_id=job.video_id, run_id=job.run_id, inference_mode=job.mode,
            artifacts=refs, entities=[e.entity_id for e in plan.entities], ready_for_geometry=not reasons,
            review_reasons=reasons)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff_manifest.json"
            path.write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
            key = f"videos/{job.video_id}/runs/{job.run_id}/handoff_manifest.json"
            store.upload(path, key, "application/json")
            manifest = ArtifactManifest(artifact_id=uid("art"), uri=key, sha256=file_hash(path), byte_count=path.stat().st_size,
                media_type="application/json", stage="handoff", run_id=job.run_id, input_hashes=[video.sha256],
                config_hash=digest(job.config), code_hash=job.config["code_hash"], created_at=now(), inference_mode=job.mode)
        with transaction() as s:
            current = assert_owner(s, job.id, token)
            s.add(Artifact(id=manifest.artifact_id, job_id=job.id, stage_run_id=stage.id,
                           name="handoff_manifest.json", manifest=manifest.model_dump(mode="json")))
            current.status = "NEEDS_REVIEW" if reasons else "COMPLETED"
            current.lease_token = current.lease_until = None
            emit(s, current, {"ready_for_geometry": not reasons, "review_reasons": reasons})
    except Exception as exc:
        error = {"code": exc.code if isinstance(exc, DomainError) else "E_INTERNAL",
                 "message": str(exc), "retryable": exc.retryable if isinstance(exc, DomainError) else False}
        with transaction() as s:
            current = s.get(Job, job_id)
            if current.lease_token == token:
                current.status = "CANCELLED" if current.cancel_requested or error["code"] == "E_CANCELLED" else "FAILED"
                current.error = error
                current.lease_token = current.lease_until = None
                if stage:
                    saved = s.get(StageRun, stage.id)
                    if saved and saved.status != "COMPLETED":
                        saved.status, saved.error = "FAILED", error
                emit(s, current, {"error": error})
        if error["code"] == "E_INTERNAL":
            import traceback
            traceback.print_exc()
    finally:
        stop.set()
        thread.join(timeout=1)

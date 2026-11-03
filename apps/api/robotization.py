"""Phase 3 submission and typed results; consumes a selected immutable ITR."""
import json
from pathlib import Path
from fastapi import APIRouter
from sqlalchemy import select

from apps.api.db import Artifact, Job, transaction
from apps.api.orchestration import schedule
from packages.common.config import settings
from packages.common.storage import Storage
from packages.common.utils import DomainError, file_hash
from packages.schemas.api import JobView
from packages.schemas.robotization import RobotizationRequest, RobotTrajectory, QualityReport, RobotizationHandoff

router = APIRouter()


@router.post("/v1/videos/{video_id}/robotize", status_code=202, response_model=JobView)
def robotize(video_id: str, body: RobotizationRequest):
    from apps.api.main import video_or_error, job_or_error, job_view, run_config
    with transaction() as session:
        video = video_or_error(session, video_id, True)
        source = job_or_error(session, body.source_job_id)
        if source.video_id != video_id or source.status not in ("COMPLETED", "NEEDS_REVIEW") or source.config.get("pipeline") != "reconstruction":
            raise DomainError("E_ROBOT_SOURCE", "Select a finished reconstruction run of this video", 409)
        existing = session.scalar(select(Job).where(Job.video_id == video_id, Job.idempotency_key == "phase3:"+body.idempotency_key))
        if existing:
            if existing.source_job_id != source.id or existing.config["robotization"]["config"] != body.config.model_dump(mode="json") or existing.config["robotization"]["allow_review_source"] != body.allow_review_source:
                raise DomainError("E_IDEMPOTENCY_CONFLICT", "Key already used with different robotization inputs", 409)
            return job_view(existing)
        handoff = session.scalar(select(Artifact).where(Artifact.job_id == source.id, Artifact.name == "phase2_handoff.json"))
        if handoff is None:
            raise DomainError("E_ROBOT_INPUTS", "Phase 2 handoff unavailable", 409)
        manifest = json.loads(Storage().read(handoff.manifest["uri"]))
        if not manifest["ready_for_robotization"] and not body.allow_review_source:
            raise DomainError("E_REVIEW_REQUIRED", "Resolve source review or explicitly allow exploratory robotization", 409)
        cfg = settings()
        asset_manifest = Path(cfg.robot_assets) / "asset_manifest.json"
        if not asset_manifest.is_file():
            raise DomainError("E_ROBOT_ASSETS", "Download official assets using python -m scripts.robot_assets", 503)
        # Runtime validation happens on the worker, which can be native or a different image.
        frozen = {**run_config(), "pipeline": "robotization", "inference_mode": source.mode,
            "robotization": {"config": body.config.model_dump(mode="json"), "allow_review_source": body.allow_review_source,
                "assets": cfg.robot_assets, "asset_manifest_sha256": file_hash(asset_manifest),
                "python": cfg.robot_python, "lerobot_python": cfg.lerobot_python}}
        return job_view(schedule(session, video, "phase3:"+body.idempotency_key, frozen, source.id))


def result(video_id, run_id, name):
    from apps.api.main import artifact_for
    artifact = artifact_for(video_id, run_id, name)
    return json.loads(Storage().read(artifact.manifest["uri"]))


@router.get("/v1/videos/{video_id}/robot-trajectory", response_model=RobotTrajectory)
def robot_trajectory(video_id: str, run_id: str):
    return result(video_id, run_id, "robot_trajectory.json")


@router.get("/v1/videos/{video_id}/robot-quality", response_model=QualityReport)
def robot_quality(video_id: str, run_id: str):
    return result(video_id, run_id, "quality_report.json")


@router.get("/v1/videos/{video_id}/phase3-handoff", response_model=RobotizationHandoff)
def robot_handoff(video_id: str, run_id: str):
    return result(video_id, run_id, "phase3_handoff.json")


@router.get("/v1/videos/{video_id}/simulation-report")
def simulation_report(video_id: str, run_id: str):
    return result(video_id, run_id, "simulation_report.json")

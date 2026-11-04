"""Phase 3 submission and typed results; consumes a selected immutable ITR."""
import json
import gzip
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


@router.post("/v1/videos/{video_id}/robotize/check")
def check_robot_inputs(video_id: str, body: RobotizationRequest):
    from apps.api.main import job_or_error
    with transaction() as session:
        source = job_or_error(session, body.source_job_id)
        if source.video_id != video_id or source.config.get("pipeline") != "reconstruction" or source.status not in ("COMPLETED", "NEEDS_REVIEW"):
            raise DomainError("E_ROBOT_SOURCE", "Select a finished reconstruction run of this video", 409)
        artifact = session.scalar(select(Artifact).where(Artifact.job_id == source.id,Artifact.name == "interaction_trajectory.json.gz"))
        if artifact is None: raise DomainError("E_ROBOT_INPUTS", "Interaction trajectory unavailable", 409)
        itr = json.loads(gzip.decompress(Storage().read(artifact.manifest["uri"])))
    cfg = body.config
    pairs = []
    for f in itr['frames']:
        if f['shot_id'] != cfg.shot_id or not cfg.start_s <= f['timestamp'] <= cfg.end_s: continue
        hand = [p for p in f['hands'] if p['entity_id']==cfg.hand_id and p['pose'] is not None]
        obj = [p for p in f['objects'] if p['entity_id']==cfg.object_id and p['pose'] is not None]
        if len(hand)==len(obj)==1:
            pairs.append((f,hand[0],obj[0]))
    reasons=[]
    if len(pairs)<2: reasons.append('Need at least two simultaneous associated hand/object poses in the selected interval')
    for previous,current in zip(pairs,pairs[1:]):
        if current[0]['timestamp']-previous[0]['timestamp']>cfg.max_gap_s+1e-9: reasons.append('Unsupported geometry gap')
        if current[0]['world_frame']!=previous[0]['world_frame']: reasons.append('World frame changes')
        if current[1]['track_id']!=previous[1]['track_id'] or current[2]['track_id']!=previous[2]['track_id']: reasons.append('Track identity changes')
    return {'ready_for_ik_attempt':not reasons,'paired_samples':len(pairs),
        'sample_times_s':[p[0]['timestamp'] for p in pairs],'reasons':sorted(set(reasons)),
        'meaning':'Input continuity only; IK, gripper, dynamics, task validity and export still require execution'}


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


@router.get("/v1/videos/{video_id}/learning-report")
def learning_report(video_id: str, run_id: str):
    return result(video_id, run_id, "rl/rl_report.json")

"""Durable Module B stages, consuming immutable artifacts from a selected layer-one run."""
import gzip
import json
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import select

from apps.api.db import Artifact, Job, StageRun, transaction
from apps.api.orchestration import assert_owner, emit
from packages.common.utils import DomainError, digest, file_hash, now, uid
from packages.schemas.models import ArtifactManifest, SemanticPlan, VideoManifest
from packages.schemas.reconstruction import (InteractionFrame, InteractionPose, InteractionTrajectory,
    LayerTwoHandoff, ReconstructionReport)
from workers.geometry.reconstruct import MaskReader, reconstruct
from workers.interaction.fusion import fuse_interactions


def read_table(store, key, directory):
    path = directory / Path(key).name
    store.download(key, path)
    return pq.read_table(path).to_pylist()


def inherit_source(job, token):
    with transaction() as session:
        assert_owner(session, job.id, token)
        existing = session.scalar(select(StageRun).where(StageRun.job_id == job.id, StageRun.stage == "reconstruction_inputs"))
        if existing:
            return existing.result
        source = session.get(Job, job.source_job_id)
        if source is None or source.video_id != job.video_id or source.status not in ("COMPLETED", "NEEDS_REVIEW"):
            raise DomainError("E_RECONSTRUCTION_SOURCE", "Selected perception run is unavailable or unfinished", 409)
        artifacts = session.scalars(select(Artifact).where(Artifact.job_id == source.id)).all()
        refs = {a.name: a.manifest["uri"] for a in artifacts}
        required = {"manifest.json", "semantic_plan.json", "tracks.parquet", "handoff_manifest.json", "video_720p_15fps.mp4"}
        if not required <= refs.keys():
            raise DomainError("E_RECONSTRUCTION_INPUTS", "Perception run lacks required layer-one artifacts", 409)
        stage = StageRun(job_id=job.id, stage="reconstruction_inputs", attempt=1, cache_key=digest(refs),
            status="COMPLETED", result=refs)
        session.add(stage)
        session.flush()
        for artifact in artifacts:
            session.add(Artifact(id=uid("art"), job_id=job.id, stage_run_id=stage.id,
                name=artifact.name, manifest=artifact.manifest))
        emit(session, session.get(Job, job.id), {"source_run_id": source.run_id, "inputs_inherited": True})
        return refs


def trajectory(manifest, plan, hands, objects, contacts, cameras, refined, report, job):
    indexed = {name: defaultdict(list) for name in ("hands", "objects", "contacts")}
    for name, rows in (("hands", hands), ("objects", objects), ("contacts", contacts)):
        for row in rows: indexed[name][row["frame_index"]].append(row)
    camera_frames = {r["frame_index"] for r in cameras}
    frames = []
    for shot in manifest.shots:
        for frame in range(shot.start_frame, shot.end_frame):
            time = frame * manifest.fps_den / manifest.fps_num
            def pose(row):
                return InteractionPose(**{key: row[key] for key in ("entity_id", "track_id", "pose", "origin", "representation")})
            frames.append(InteractionFrame(shot_id=shot.shot_id, world_frame=f"world:{manifest.video_id}:{shot.shot_id}",
                frame_index=frame, timestamp=time, camera_frame_index=frame if frame in camera_frames else None,
                hands=[pose(r) for r in indexed["hands"][frame]], objects=[pose(r) for r in indexed["objects"][frame]],
                contacts=indexed["contacts"][frame], current_action_ids=[a.action_id for a in plan.actions if a.start_s <= time < a.end_s]))
    return InteractionTrajectory(video_id=manifest.video_id, run_id=job.run_id, source_run_id=report.source_run_id,
        task=plan.task, canonical_skill=plan.canonical_skill, entities=plan.entities, action_graph=plan.action_graph,
        refined_actions=refined, frames=frames, quality=report)


def execute(job, token, store):
    from workers.pipeline import Recorder, publish_directory, stage_start
    inputs = inherit_source(job, token)
    with transaction() as session:
        source = session.get(Job, job.source_job_id)
        input_artifacts = session.scalars(select(Artifact).where(Artifact.job_id == source.id)).all()
    input_hashes = sorted({a.manifest["sha256"] for a in input_artifacts})
    cfg = job.config["reconstruction"]
    outputs = {}
    stage = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = VideoManifest.model_validate_json(store.read(inputs["manifest.json"]))
            plan = SemanticPlan.model_validate_json(store.read(inputs["semantic_plan.json"]))
            masks = MaskReader(store.read)
            for name in ("geometry", "interaction", "interaction_trajectory"):
                cache_key = digest({"stage": name, "inputs": input_hashes, "config": job.config,
                    "upstream": outputs, "source_run_id": source.run_id,
                    "run_id": job.run_id if name == "interaction_trajectory" else None})
                stage, cached = stage_start(job.id, token, name, cache_key)
                if not cached:
                    output = root / name
                    output.mkdir(exist_ok=True)
                    if name == "geometry":
                        video = root / "video.mp4"
                        store.download(inputs["video_720p_15fps.mp4"], video)
                        tracks = read_table(store, inputs["tracks.parquet"], root)
                        recorder = Recorder(job, stage, token, store)
                        request_key = digest({"inputs": input_hashes, "config": cfg})
                        event = {"model": cfg["provider_fingerprint"]["model"], "request_key": request_key, "attempt": stage.attempt}
                        recorder({**event, "status": "started"})
                        started = time.monotonic()
                        try:
                            result = reconstruct(video, manifest, plan, tracks, masks, output, cfg, source.run_id, job.mode)
                        except Exception as exc:
                            logs = {str(path.relative_to(output)): path.read_text(errors="replace")[-16000:]
                                    for path in output.rglob("*.log")}
                            recorder({**event, "status": "failed", "error": {"code": getattr(exc, "code", "E_GEOMETRY_RUNTIME"), "message": str(exc)},
                                "raw_output": json.dumps({"error": str(exc), "runtime_logs": logs})})
                            raise
                        recorder({**event, "status": "completed", "latency_ms": round((time.monotonic()-started)*1000),
                            "usage": {"sampled_frames": result.camera_frames, "local_inference": True,
                                "body_backend": cfg["body_backend"]}, "raw_output": result.model_dump_json()})
                    elif name == "interaction":
                        tracks = read_table(store, inputs["tracks.parquet"], root)
                        hands = read_table(store, outputs["geometry"]["hand_pose.parquet"], root)
                        objects = read_table(store, outputs["geometry"]["object_pose.parquet"], root)
                        fuse_interactions(manifest, plan, tracks, masks, hands, objects, output, cfg, job.mode)
                    else:
                        geometry = outputs["geometry"]
                        interaction = outputs["interaction"]
                        report = ReconstructionReport.model_validate_json(store.read(geometry["geometry_report.json"]))
                        interaction_report = json.loads(store.read(interaction["interaction_report.json"]))
                        report.contact_frames = interaction_report["contact_frames"]
                        report.contact_events = interaction_report["contact_events"]
                        report.review_reasons += interaction_report["review_reasons"]
                        report.review_reasons += json.loads(store.read(inputs["handoff_manifest.json"]))["review_reasons"]
                        hands = read_table(store, geometry["hand_pose.parquet"], root)
                        objects = read_table(store, geometry["object_pose.parquet"], root)
                        contacts = read_table(store, interaction["contacts.parquet"], root)
                        cameras = read_table(store, geometry["cameras.parquet"], root)
                        refined = json.loads(store.read(interaction["refined_actions.json"]))
                        itr = trajectory(manifest, plan, hands, objects, contacts, cameras, refined, report, job)
                        (output / "interaction_trajectory.json.gz").write_bytes(gzip.compress(itr.model_dump_json().encode(), mtime=0))
                        (output / "reconstruction_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
                    refs = publish_directory(job, stage, output, token, store, input_hashes,
                        model=cfg["provider_fingerprint"]["model"] if name == "geometry" else "contact-fusion-v1" if name == "interaction" else None)
                    with transaction() as session:
                        current = assert_owner(session, job.id, token)
                        saved = session.get(StageRun, stage.id)
                        saved.status, saved.result = "COMPLETED", refs
                        emit(session, current, {"stage_completed": name})
                    stage.result = refs
                outputs[name] = stage.result
            report = ReconstructionReport.model_validate_json(store.read(outputs["interaction_trajectory"]["reconstruction_report.json"]))
            refs = {f"layer_one/{name}": key for name, key in inputs.items()}
            refs.update({f"{name}/{filename}": key for name, files in outputs.items() for filename, key in files.items()})
            handoff = LayerTwoHandoff(video_id=job.video_id, run_id=job.run_id, source_run_id=source.run_id,
                inference_mode=job.mode, artifacts=refs, ready_for_robotization=False, review_reasons=report.review_reasons)
            path = root / "phase2_handoff.json"
            path.write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
            key = f"videos/{job.video_id}/runs/{job.run_id}/phase2_handoff.json"
            store.upload(path, key, "application/json", reuse_identical=True)
            artifact = ArtifactManifest(artifact_id=uid("art"), uri=key, sha256=file_hash(path), byte_count=path.stat().st_size,
                media_type="application/json", stage="phase2_handoff", run_id=job.run_id, input_hashes=input_hashes,
                config_hash=digest(job.config), code_hash=job.config["code_hash"], created_at=now(), inference_mode=job.mode)
            with transaction() as session:
                current = assert_owner(session, job.id, token)
                session.add(Artifact(id=artifact.artifact_id, job_id=job.id, stage_run_id=stage.id,
                    name="phase2_handoff.json", manifest=artifact.model_dump(mode="json")))
                current.status = "NEEDS_REVIEW"
                current.lease_token = current.lease_until = None
                emit(session, current, {"ready_for_robotization": False, "review_reasons": report.review_reasons})
    except Exception as exc:
        if stage:
            with transaction() as session:
                current = session.get(Job, job.id)
                saved = session.get(StageRun, stage.id)
                if current.lease_token == token and saved.status != "COMPLETED":
                    saved.status, saved.error = "FAILED", {"code": getattr(exc, "code", "E_INTERNAL"), "message": str(exc)}
        raise

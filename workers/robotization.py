"""Leased Phase 3 worker with isolated optional native robot/runtime execution."""
import gzip
import json
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from apps.api.db import Artifact, Job, StageRun, Video, ModelExecution, CorrectionRecord, transaction
from apps.api.orchestration import assert_owner, emit
from packages.common.utils import DomainError, digest, uid


def metric_hint(store, refs, root, hand_id):
    """Meters per reconstruction unit from the person in the video, when geometry provides it."""
    from packages.robot.metric import estimate_scale
    alignments = json.loads(store.read(refs["alignments.json"])) if "alignments.json" in refs else []
    hands = []
    if "hand_pose.parquet" in refs:
        import pyarrow.parquet as pq
        path = root / "hand_pose.parquet"
        store.download(refs["hand_pose.parquet"], path)
        hands = pq.read_table(path, columns=["entity_id", "pose", "points_world"]).to_pylist()
    return estimate_scale(alignments, hands, hand_id)


def execute(job, token, store):
    from workers.pipeline import stage_start, publish_directory
    runtime = job.config["robotization"]
    with transaction() as session:
        source = session.get(Job, job.source_job_id)
        if source is None or source.config.get("pipeline") != "reconstruction" or source.status not in ("COMPLETED", "NEEDS_REVIEW"):
            raise DomainError("E_ROBOT_SOURCE", "Source reconstruction is unavailable", 409)
        artifacts = session.scalars(select(Artifact).where(Artifact.job_id == source.id)).all()
        video = session.get(Video,job.video_id)
        provenance = {"video_id":job.video_id,"source_sha256":video.sha256,"source_license":video.provenance,
            "source_reconstruction_job_id":source.id,"source_reconstruction_run_id":source.run_id,
            "compiler_code_hash":job.config['code_hash'],
            "input_artifact_hashes":{a.name:a.manifest['sha256'] for a in artifacts},
            "geometry_provider":source.config.get('reconstruction',{}).get('provider_fingerprint'),
            "model_requests":[],"corrections":[]}
        ancestor = source
        seen = set()
        while ancestor and ancestor.id not in seen:
            seen.add(ancestor.id)
            for model in session.scalars(select(ModelExecution).where(ModelExecution.job_id==ancestor.id)).all():
                provenance['model_requests'].append({k:model.data.get(k) for k in
                    ('model_run_id','model','revision','input_hash','status','request_id','latency_ms','usage','actual_cost_usd')})
            for correction in session.scalars(select(CorrectionRecord).where(CorrectionRecord.job_id==ancestor.id)).all():
                provenance['corrections'].extend(correction.data.get('batch', [correction.data]))
            ancestor = session.get(Job,ancestor.source_job_id) if ancestor.source_job_id else None
    refs = {a.name: a.manifest["uri"] for a in artifacts}
    if not {"interaction_trajectory.json.gz", "phase2_handoff.json"} <= refs.keys():
        raise DomainError("E_ROBOT_INPUTS", "ITR and handoff required", 409)
    hashes = sorted({a.manifest["sha256"] for a in artifacts})
    # Run-specific final manifest/export lineage; no cross-run ambiguity.
    key = digest({"inputs": hashes, "config": job.config, "run": job.run_id})
    with transaction() as session:
        assert_owner(session, job.id, token)
        inherited = session.scalar(select(StageRun).where(StageRun.job_id == job.id, StageRun.stage == "robotization_inputs"))
        if inherited is None:
            inherited = StageRun(job_id=job.id, stage="robotization_inputs", attempt=1, cache_key=digest(hashes), status="COMPLETED", result=refs)
            session.add(inherited)
            session.flush()
            for artifact in artifacts:
                session.add(Artifact(id=uid("art"), job_id=job.id, stage_run_id=inherited.id, name=artifact.name, manifest=artifact.manifest))
    stage, cached = stage_start(job.id, token, "robotization", key)
    try:
        if not cached:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request = {"itr": json.loads(gzip.decompress(store.read(refs["interaction_trajectory.json.gz"]))),
                    "handoff": json.loads(store.read(refs["phase2_handoff.json"])), "runtime": runtime,
                    "run_id": job.run_id,"provenance":provenance}
                if runtime["config"].get("mode") == "skill":
                    request["metric_hint"] = metric_hint(store, refs, root, runtime["config"]["hand_id"])
                    if "semantic_plan.json" in refs:
                        request["semantic_plan"] = json.loads(store.read(refs["semantic_plan.json"]))
                request_path = root / "request.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                output = root / "output"
                output.mkdir()
                if runtime["python"]:
                    completed = subprocess.run([runtime["python"], "-m", "workers.robotization_entry", "--request", str(request_path),
                        "--output", str(output)], capture_output=True, timeout=1800, env={**os.environ, "HF_HUB_OFFLINE": "1"})
                    (output / "robot_stdout.log").write_bytes(completed.stdout)
                    (output / "robot_stderr.log").write_bytes(completed.stderr)
                    if completed.returncode:
                        # The temporary directory, and the logs in it, do not outlive this block.
                        reported = output / "error.json"
                        if reported.is_file():
                            failure = json.loads(reported.read_text(encoding="utf-8"))
                            raise DomainError(failure["code"], failure["message"], failure["status"])
                        tail = completed.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no error output"]
                        raise DomainError("E_ROBOT_RUNTIME", f"Robot runtime failed: {tail[0][:500]}", 503)
                else:
                    from workers.robotization_entry import run
                    run(request, output)
                handoff = json.loads((output / "phase3_handoff.json").read_text())
                # Resolve the final immutable stage prefix before publication.
                handoff["artifacts"] = {p.relative_to(output).as_posix():
                    f"videos/{job.video_id}/runs/{job.run_id}/{stage.id}/{stage.stage}/{p.relative_to(output).as_posix()}"
                    for p in output.rglob("*") if p.is_file() and p.name != "phase3_handoff.json"}
                (output / "phase3_handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
                published = publish_directory(job, stage, output, token, store, hashes, model="franka-panda-mujoco")
                # Publish actual storage references in the handoff, not local file paths.
                handoff["artifacts"] = {n: k for n, k in published.items() if n != "phase3_handoff.json"}
                # Handoff is emitted as a separate immutable stage artifact below.
                final = root / "final"
                final.mkdir()
                (final / "baseline_handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
                published.update(publish_directory(job, stage, final, token, store, hashes))
                with transaction() as session:
                    assert_owner(session, job.id, token)
                    saved = session.get(StageRun, stage.id)
                    saved.status, saved.result = "COMPLETED", published
                stage.result = published
        quality = json.loads(store.read(stage.result["quality_report.json"]))
        with transaction() as session:
            current = assert_owner(session, job.id, token)
            current.status = "COMPLETED" if quality["classification"] == "Gold" else "NEEDS_REVIEW"
            current.lease_token = current.lease_until = None
            emit(session, current, {"quality": quality["classification"], "accepted_training_subset": quality["accepted_training_subset"]})
    except Exception as exc:
        with transaction() as session:
            current = session.get(Job, job.id)
            saved = session.get(StageRun, stage.id)
            if current.lease_token == token and saved.status != "COMPLETED":
                saved.status, saved.error = "FAILED", {"code": getattr(exc, "code", "E_ROBOT_RUNTIME"), "message": str(exc)}
        raise

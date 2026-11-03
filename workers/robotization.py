"""Leased Phase 3 worker with isolated optional native robot/runtime execution."""
import gzip
import json
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from apps.api.db import Artifact, Job, StageRun, transaction
from apps.api.orchestration import assert_owner, emit
from packages.common.utils import DomainError, digest, uid


def execute(job, token, store):
    from workers.pipeline import stage_start, publish_directory
    runtime = job.config["robotization"]
    with transaction() as session:
        source = session.get(Job, job.source_job_id)
        if source is None or source.config.get("pipeline") != "reconstruction" or source.status not in ("COMPLETED", "NEEDS_REVIEW"):
            raise DomainError("E_ROBOT_SOURCE", "Source reconstruction is unavailable", 409)
        artifacts = session.scalars(select(Artifact).where(Artifact.job_id == source.id)).all()
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
                    "run_id": job.run_id}
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
                        raise DomainError("E_ROBOT_RUNTIME", "Robot runtime failed; inspect worker logs", 503)
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

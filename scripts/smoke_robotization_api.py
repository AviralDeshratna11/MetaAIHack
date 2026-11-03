"""HTTP/storage/leased-native-worker Phase 3 integration on fixture reconstruction.

Use with the Docker worker stopped: RQ's fork worker is not supported on Windows.
The native call uses the same production claim/heartbeat/publish path, not a fake API.
"""
import argparse
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58001")
    parser.add_argument("--source-report", default="eval/reports/phase2-reverification.json")
    parser.add_argument("--report", default="eval/reports/phase3-api-smoke.json")
    parser.add_argument("--worker-mode", choices=["native", "queue"], default="native")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.api, timeout=120)
    def call(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        if not r.is_success: raise RuntimeError(r.text)
        return r.json()
    source = json.loads(Path(args.source_report).read_text())
    video_id = source["video_id"]
    source_artifacts = call("GET", f"/v1/videos/{video_id}/artifacts?run_id={source['run_id']}")["artifacts"]
    itr_artifact = next(a for a in source_artifacts if a["name"] == "interaction_trajectory.json.gz")
    itr = json.loads(gzip.decompress(client.get(itr_artifact["url"]).content))
    assert itr["quality"]["inference_mode"] == "fixture", "Never use synthetic acceptance for live video"
    observed = [f for f in itr["frames"] if any(h["pose"] for h in f["hands"]) and any(o["pose"] for o in f["objects"])]
    pair = next((a,b) for a,b in zip(observed, observed[1:]) if b["timestamp"]-a["timestamp"] <= 1)
    a, b = pair
    config = {"hand_id": next(h["entity_id"] for h in a["hands"] if h["pose"]),
        "object_id": next(o["entity_id"] for o in a["objects"] if o["pose"]), "shot_id": a["shot_id"],
        "start_s": a["timestamp"], "end_s": b["timestamp"]+.001, "max_gap_s": 1,
        "workspace_extent_m": .02, "workspace_center_m": [.42, 0, .55], "initial_gripper": "unknown"}
    payload = {"source_job_id": source["job_id"], "idempotency_key": "api-smoke-"+str(time.time_ns()),
               "allow_review_source": True, "config": config}
    gated = client.post(f"/v1/videos/{video_id}/robotize", json={**payload, "allow_review_source": False})
    assert gated.status_code == 409 and gated.json()["code"] == "E_REVIEW_REQUIRED"
    queued = call("POST", f"/v1/videos/{video_id}/robotize", json=payload)
    duplicate = call("POST", f"/v1/videos/{video_id}/robotize", json=payload)
    assert queued["job_id"] == duplicate["job_id"]
    conflict = client.post(f"/v1/videos/{video_id}/robotize", json={**payload, "config": {**config, "control_hz": 15}})
    assert conflict.status_code == 409
    # Docker binds PostgreSQL to IPv4 loopback. Avoid an IPv6/SSL negotiation
    # stall on Windows while leaving configured remote database URLs intact.
    if args.worker_mode == "native":
        from packages.common.config import settings
        cfg = settings()
        if "@localhost:55432/" in cfg.database_url:
            os.environ["DATABASE_URL"] = cfg.database_url.replace("@localhost:55432/", "@127.0.0.1:55432/")+"?sslmode=disable&connect_timeout=5"
            settings.cache_clear()
        from workers.pipeline import run_job
        run_job(queued["job_id"])
    else:
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            current = call("GET", f"/v1/jobs/{queued['job_id']}")
            if current["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"): break
            time.sleep(1)
    job = call("GET", f"/v1/jobs/{queued['job_id']}")
    assert job["status"] == "NEEDS_REVIEW", job
    suffix = f"?run_id={job['run_id']}"
    quality = call("GET", f"/v1/videos/{video_id}/robot-quality{suffix}")
    trajectory = call("GET", f"/v1/videos/{video_id}/robot-trajectory{suffix}")
    simulation = call("GET", f"/v1/videos/{video_id}/simulation-report{suffix}")
    handoff = call("GET", f"/v1/videos/{video_id}/phase3-handoff{suffix}")
    assert trajectory["source_run_id"] == source["run_id"] and trajectory["run_id"] == job["run_id"]
    assert handoff["artifacts"] and quality["classification"] == "Reject" and not quality["accepted_training_subset"]
    assert simulation["physics_stepped"]
    exports = call("GET", f"/v1/videos/{video_id}/artifacts{suffix}")["artifacts"]
    export_file = next(a for a in exports if a["name"] == "export_report.json")
    export_report = client.get(export_file["url"]).json()
    assert export_report["roundtrip_passed"] is False
    error_log = next(a for a in exports if a["name"] == "export/export_stderr.log")
    assert "Unknown gripper commands cannot be exported" in client.get(error_log["url"]).text
    artifacts = call("GET", f"/v1/videos/{video_id}/artifacts{suffix}")["artifacts"]
    for artifact in artifacts:
        response = client.get(artifact["url"])
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
    # A correction/reconstruction endpoint must reject this downstream source.
    rejected = client.post(f"/v1/videos/{video_id}/reconstruct", json={"source_job_id": job["job_id"], "idempotency_key": "invalid-phase3-source"})
    assert rejected.status_code == 409
    after = call("GET", f"/v1/videos/{video_id}/artifacts?run_id={source['run_id']}")["artifacts"]
    assert {a["name"]: (a["uri"], a["sha256"]) for a in after} == {a["name"]: (a["uri"], a["sha256"]) for a in source_artifacts}
    report = {"status": "passed", "inference_mode": "fixture", "real_model_calls": 0, "worker_mode": args.worker_mode,
        "job_id": job["job_id"], "run_id": job["run_id"], "video_id": video_id, "source_run_id": source["run_id"],
        "artifact_count": len(artifacts), "frames": len(trajectory["frames"]), "quality": quality, "export": export_report,
        "checks": ["review gate", "idempotency", "config conflict", "leased worker", "source immutability", "typed APIs",
                   "inherited artifacts", "artifact hashes", "physics replay", "unknown gripper prevents acceptance", "invalid pipeline source rejected"]}
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

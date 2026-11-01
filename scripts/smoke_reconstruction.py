"""Public HTTP / queue / storage acceptance for Module B, strictly fixture-only."""
import argparse
import gzip
import hashlib
import json
import time
from pathlib import Path

import httpx

from packages.schemas.reconstruction import GeometryWindow, InteractionTrajectory, LayerTwoHandoff, ReconstructionReport


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--source-job")
    parser.add_argument("--report", default="eval/reports/phase2-smoke.json")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.api, timeout=120)
    def call(method, path, **kwargs):
        result = client.request(method, path, **kwargs)
        result.raise_for_status()
        return result.json()
    def wait(job_id):
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            job = call("GET", f"/v1/jobs/{job_id}")
            if job["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"):
                assert job["status"] == "NEEDS_REVIEW", job
                return job
            time.sleep(1)
        raise AssertionError("Reconstruction timed out")
    assert call("GET", "/health/ready")["inference_mode"] == "fixture", "Smoke must never spend live credits"
    if args.source_job:
        source = call("GET", f"/v1/jobs/{args.source_job}")
    else:
        video = client.get("/v1/demo-source")
        video.raise_for_status()
        created = call("POST", "/v1/videos", json={"filename": "phase2-synthetic.mp4", "byte_count": len(video.content),
            "sha256": hashlib.sha256(video.content).hexdigest(), "provenance": {"rights_status": "synthetic", "uploader": "phase2-smoke"}})
        client.put(created["upload_url"], content=video.content, headers=created["upload_headers"]).raise_for_status()
        video_id = created["video_id"]
        call("POST", f"/v1/videos/{video_id}/complete-upload")
        queued = call("POST", f"/v1/videos/{video_id}/process", json={"idempotency_key": "phase2-smoke-source"})
        source = wait(queued["job_id"])
    assert source["inference_mode"] == "fixture" and source.get("pipeline", "perception") == "perception"
    video_id = source["video_id"]
    payload = {"source_job_id": source["job_id"], "idempotency_key": "phase2-smoke",
        "config": {"backend": "fixture", "max_frames_per_shot": 16, "max_points_per_entity": 64}}
    start = time.monotonic()
    queued = call("POST", f"/v1/videos/{video_id}/reconstruct", json=payload)
    duplicate = call("POST", f"/v1/videos/{video_id}/reconstruct", json=payload)
    assert queued["job_id"] == duplicate["job_id"]
    conflict = client.post(f"/v1/videos/{video_id}/reconstruct", json={**payload, "config": {"backend": "fixture"}})
    assert conflict.status_code == 409 and conflict.json()["code"] == "E_IDEMPOTENCY_CONFLICT"
    job = wait(queued["job_id"])
    suffix = f"?run_id={job['run_id']}"
    report = ReconstructionReport.model_validate(call("GET", f"/v1/videos/{video_id}/geometry-report{suffix}"))
    handoff = LayerTwoHandoff.model_validate(call("GET", f"/v1/videos/{video_id}/phase2-handoff{suffix}"))
    assert not handoff.ready_for_robotization and not handoff.metric_scale_valid
    assert report.camera_frames == 16 and report.hand_pose_frames > 0 and report.object_pose_frames > 0
    assert report.source_run_id == source["run_id"]
    window = GeometryWindow.model_validate(call("GET", f"/v1/videos/{video_id}/geometry{suffix}&limit=2000"))
    assert window.total == 180 and len(window.hands) == 180 and len(window.objects) == 360
    assert any(row.origin == "missing" for row in window.hands)
    assert all(row.pose is None or row.origin == "synthetic" for row in window.hands)
    contact_window = GeometryWindow.model_validate(call("GET", f"/v1/videos/{video_id}/contacts{suffix}&start_s=1&end_s=2"))
    assert all(1 <= row.timestamp <= 2 for row in contact_window.contacts)
    files = call("GET", f"/v1/videos/{video_id}/artifacts{suffix}")["artifacts"]
    contents = {}
    for artifact in files:
        response = client.get(artifact["url"])
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
        contents[artifact["name"]] = response.content
    itr = InteractionTrajectory.model_validate_json(gzip.decompress(contents["interaction_trajectory.json.gz"]))
    assert itr.run_id == job["run_id"] and len(itr.frames) == 180
    assert len(itr.refined_actions) == 7 and not itr.metric_scale_valid
    # Reuse geometry/contact stages, but regenerate the run-specific ITR and handoff.
    second = call("POST", f"/v1/videos/{video_id}/reconstruct", json={**payload, "idempotency_key": "phase2-cache-check"})
    second = wait(second["job_id"])
    second_files = call("GET", f"/v1/videos/{video_id}/artifacts?run_id={second['run_id']}")["artifacts"]
    refs, second_refs = ({a["name"]: a["uri"] for a in group} for group in (files, second_files))
    assert refs["cameras.parquet"] == second_refs["cameras.parquet"]
    assert refs["contacts.parquet"] == second_refs["contacts.parquet"]
    assert refs["interaction_trajectory.json.gz"] != second_refs["interaction_trajectory.json.gz"]
    second_itr = next(a for a in second_files if a["name"] == "interaction_trajectory.json.gz")
    assert InteractionTrajectory.model_validate_json(gzip.decompress(client.get(second_itr["url"]).content)).run_id == second["run_id"]
    assert call("GET", f"/v1/videos/{video_id}/phase2-handoff{suffix}") == handoff.model_dump(mode="json")
    events = client.get(f"/v1/jobs/{job['job_id']}/events")
    events.raise_for_status()
    assert "interaction_trajectory" in events.text and "NEEDS_REVIEW" in events.text
    output = {"schema_version": "0.2.0", "status": "passed", "inference_mode": "fixture", "real_model_calls": 0,
        "video_id": video_id, "source_job_id": source["job_id"], "job_id": job["job_id"], "run_id": job["run_id"],
        "artifact_count": len(files), "camera_frames": report.camera_frames, "hand_pose_frames": report.hand_pose_frames,
        "object_pose_frames": report.object_pose_frames, "itr_frames": len(itr.frames),
        "contact_frames": report.contact_frames, "elapsed_s": round(time.monotonic()-start, 3),
        "checks": ["immutable source inheritance", "queue stages", "idempotency", "conflicting config rejection", "geometry contracts",
            "missing geometry", "object-relative poses", "contact windows", "artifact SHA-256", "typed ITR", "persisted SSE",
            "geometry/contact cache reuse", "run-specific ITR lineage", "original handoff immutability", "relative-scale/review gate"]}
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

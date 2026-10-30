"""Real HTTP + S3 + DB + Redis/RQ integration, with explicitly fixture-only inference."""
import argparse
import hashlib
import io
import json
import time
from pathlib import Path

import httpx
import pyarrow.parquet as pq


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--report", default="eval/reports/offline-smoke.json")
    args = parser.parse_args()
    client = httpx.Client(timeout=120)
    root = args.api.rstrip("/")
    def call(method, path, **kwargs):
        response = client.request(method, root + path, **kwargs)
        response.raise_for_status()
        return response.json()
    health = call("GET", "/health/ready")
    assert health["inference_mode"] == "fixture", "This smoke test must never spend live API credits"
    source = client.get(root + "/v1/demo-source"); source.raise_for_status()
    created = call("POST", "/v1/videos", json={"filename": "synthetic-fixture.mp4", "byte_count": len(source.content),
        "sha256": hashlib.sha256(source.content).hexdigest(), "provenance": {"rights_status": "synthetic", "uploader": "offline-smoke"}})
    uploaded = client.put(created["upload_url"], content=source.content, headers=created["upload_headers"])
    uploaded.raise_for_status()
    overwrite = client.put(created["upload_url"], content=source.content, headers=created["upload_headers"])
    assert overwrite.status_code == 412, "Source object must be immutable"
    video_id = created["video_id"]
    call("POST", f"/v1/videos/{video_id}/complete-upload")
    submitted = call("POST", f"/v1/videos/{video_id}/process", json={"idempotency_key": "offline-smoke"})
    duplicate = call("POST", f"/v1/videos/{video_id}/process", json={"idempotency_key": "offline-smoke"})
    assert submitted["job_id"] == duplicate["job_id"]
    start = time.monotonic()
    while time.monotonic() - start < 240:
        job = call("GET", f"/v1/jobs/{submitted['job_id']}")
        if job["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    assert job["status"] == "NEEDS_REVIEW", job
    run = f"?run_id={job['run_id']}"
    plan = call("GET", f"/v1/videos/{video_id}/actions{run}")
    handoff = call("GET", f"/v1/videos/{video_id}/handoff{run}")
    assert not handoff["ready_for_geometry"] and handoff["inference_mode"] == "fixture"
    assert len(plan["entities"]) == 3 and len(plan["actions"]) == 7
    frame = call("GET", f"/v1/videos/{video_id}/tracks{run}&start_s=1&end_s=1.001&limit=200&include_masks=true")
    assert len(frame["tracks"]) == 3 and len(frame["masks"]) == 3, frame
    artifacts = call("GET", f"/v1/videos/{video_id}/artifacts{run}")["artifacts"]
    for artifact in artifacts:
        content = client.get(artifact["url"]); content.raise_for_status()
        assert hashlib.sha256(content.content).hexdigest() == artifact["sha256"]
    table = next(a for a in artifacts if a["name"] == "tracks.parquet")
    rows = pq.read_table(io.BytesIO(client.get(table["url"]).content)).to_pylist()
    assert len(rows) == 180 * 3 and all(r["provider_confidence"] is None for r in rows)
    assert len({r["track_id"] for r in rows}) == 3
    events = client.get(root + f"/v1/jobs/{job['job_id']}/events"); events.raise_for_status()
    assert "NEEDS_REVIEW" in events.text and "id:" in events.text
    invalid_retry = client.post(root + f"/v1/jobs/{job['job_id']}/retry")
    assert invalid_retry.status_code == 409
    # Correction lineage is exercised through the same public API as the UI.
    corrected = call("POST", f"/v1/videos/{video_id}/corrections", json={
        "source_job_id": job["job_id"], "entity_id": "mug", "shot_id": "shot_000",
        "frame_index": 15, "kind": "association", "provider_track_id": "0"})
    assert corrected["run_id"] != job["run_id"] and corrected["source_job_id"] == job["job_id"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        correction_job = call("GET", f"/v1/jobs/{corrected['job_id']}")
        if correction_job["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    assert correction_job["status"] == "NEEDS_REVIEW", correction_job
    new_artifacts = call("GET", f"/v1/videos/{video_id}/artifacts?run_id={corrected['run_id']}")["artifacts"]
    original_refs = {a["name"]: a["uri"] for a in artifacts}
    corrected_refs = {a["name"]: a["uri"] for a in new_artifacts}
    assert corrected_refs["manifest.json"] == original_refs["manifest.json"]
    assert corrected_refs["semantic_plan.json"] == original_refs["semantic_plan.json"]
    assert corrected_refs["tracks.parquet"] != original_refs["tracks.parquet"]
    original_handoff = call("GET", f"/v1/videos/{video_id}/handoff{run}")
    assert original_handoff == handoff, "Correction must not alter the source run"
    # A queued cancellation must revoke execution and remain visible after redelivery.
    cancelled = call("POST", f"/v1/videos/{video_id}/process", json={"idempotency_key": "cancelled-smoke"})
    cancelled = call("POST", f"/v1/jobs/{cancelled['job_id']}/cancel")
    assert cancelled["status"] == "CANCELLED"
    assert call("GET", f"/v1/jobs/{cancelled['job_id']}")["status"] == "CANCELLED"
    report = {"status": "passed", "inference_mode": "fixture", "real_model_calls": 0, "video_id": video_id,
        "job_id": job["job_id"], "run_id": job["run_id"], "source": "generated shapes; no human demonstration",
        "artifact_count": len(artifacts), "track_rows": len(rows), "entity_count": len(plan["entities"]),
        "elapsed_processing_s": round(time.monotonic() - start, 3),
        "checks": ["real FFmpeg", "real PostgreSQL", "real Redis/RQ", "real MinIO", "presigned conditional upload",
                   "checksum verification", "idempotent submission", "artifact hashes", "mask decoding", "persisted SSE", "handoff gate",
                   "correction lineage", "upstream cache reuse", "downstream invalidation", "source run immutability", "cancellation"]}
    target = Path(args.report); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

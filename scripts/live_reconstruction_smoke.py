"""Real reconstruction through HTTP/queue using a previously completed live perception run."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--source-report", default="eval/reports/baseline-phase1-live.json")
    parser.add_argument("--report", default="eval/reports/live-phase2-geometry.json")
    parser.add_argument("--key", default="verified-real-geometry-v1")
    args = parser.parse_args()
    source = json.loads(Path(args.source_report).read_text())
    assert source["api_inference_mode"] == "live"
    client = httpx.Client(base_url=args.api, timeout=240)
    def call(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        if not r.is_success: raise RuntimeError(r.text)
        return r.json()
    assert call("GET", "/health/ready")["inference_mode"] == "live"
    started = time.monotonic()
    job = call("POST", f"/v1/videos/{source['video_id']}/reconstruct", json={"source_job_id": source["job_id"],
        "idempotency_key": args.key, "allow_review_source": True, "config": {"backend": "vggt", "body_backend": "sam3d",
        "memory_mode": "low_vram", "image_size": 224, "max_total_frames": 4, "max_frames_per_shot": 4}})
    result = {"status": "running", "job_id": job["job_id"], "run_id": job["run_id"], "video_id": source["video_id"],
        "source_run_id": source["run_id"], "inference_mode": "live", "hosted_inference_requests": 0}
    target = Path(args.report)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    while time.monotonic()-started < 1800:
        detail = call("GET", f"/v1/jobs/{job['job_id']}")
        if detail["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"): break
        time.sleep(2)
    result.update(job_status=detail["status"], elapsed_s=round(time.monotonic()-started, 3))
    if detail["status"] not in ("COMPLETED", "NEEDS_REVIEW"):
        result.update(status="failed", error=detail.get("error"))
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise SystemExit(json.dumps(result))
    suffix = f"?run_id={job['run_id']}"
    artifacts = call("GET", f"/v1/videos/{source['video_id']}/artifacts{suffix}")["artifacts"]
    runtime = []
    count = 0
    for artifact in artifacts:
        response = client.get(artifact["url"])
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
        count += 1
        if artifact["name"].endswith("runtime_report.json"):
            runtime.append(response.json())
    assert runtime and all(r["status"] == "completed" and r["body_backend"] == "sam3d" for r in runtime)
    result.update(status="completed_with_review", artifact_hashes_verified=count, runtime=runtime,
        geometry=call("GET", f"/v1/videos/{source['video_id']}/geometry-report{suffix}"),
        handoff=call("GET", f"/v1/videos/{source['video_id']}/phase2-handoff{suffix}"))
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("geometry", "handoff")}))


if __name__ == "__main__":
    main()

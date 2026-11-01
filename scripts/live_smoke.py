"""Bounded real-video acceptance. Never submits fixture inference on real footage."""
import argparse
import gzip
import hashlib
import io
import json
import time
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from packages.common.config import settings
from packages.common.utils import file_hash
from packages.schemas.models import LayerOneHandoffManifest, SemanticPlan, TrackFrame
from packages.video.masks import decode_rle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/golden/pouring.mp4"))
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--report", type=Path, default=Path("eval/reports/live-smoke.json"))
    parser.add_argument("--source-uri")
    parser.add_argument("--license")
    parser.add_argument("--rights", choices=["licensed", "team_recorded", "user_supplied"])
    parser.add_argument("--idempotency-key", default="real-live-smoke-v1")
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit("Real source video is absent; import authorized footage first")
    cfg = settings()
    client = httpx.Client(base_url=args.api, timeout=120)
    def call(method, path, **kwargs):
        result = client.request(method, path, **kwargs)
        result.raise_for_status()
        return result.json()
    health = call("GET", "/health/ready")
    sha = file_hash(source)
    manifest_path = Path("eval/golden/manifest.json")
    assets = json.loads(manifest_path.read_text())["clips"] if manifest_path.exists() else []
    asset = next((clip for clip in assets if clip.get("sha256") == sha), None)
    if asset:
        provenance = {k: asset.get(k) for k in ("source_uri", "rights_status", "license", "consent")}
    elif args.source_uri and args.rights:
        provenance = {"source_uri": args.source_uri, "rights_status": args.rights, "license": args.license, "consent": None}
    else:
        raise SystemExit("Supply --source-uri and --rights for media not registered in the golden manifest")
    provenance["uploader"] = "live-smoke"
    previous = json.loads(args.report.read_text()) if args.report.exists() else {}
    report = {"status": "preparing", "requested_inference_mode": "live", "source": str(source), "source_sha256": sha,
        "api_inference_mode": health["inference_mode"], "checks": [], "blockers": [], "live_inference_submitted": False}
    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    # Reuse the already validated upload when resuming after credential setup.
    video_id = previous.get("video_id") if previous.get("source_sha256") == sha and previous.get("api") == args.api else None
    if not video_id:
        created = call("POST", "/v1/videos", json={"filename": source.name, "byte_count": source.stat().st_size,
            "sha256": sha, "provenance": provenance})
        with source.open("rb") as stream:
            uploaded = client.put(created["upload_url"], content=stream, headers=created["upload_headers"])
        uploaded.raise_for_status()
        video_id = created["video_id"]
    completed = call("POST", f"/v1/videos/{video_id}/complete-upload")
    report.update(video_id=video_id, api=args.api, upload_status=completed["status"])
    report["checks"] += ["real video upload", "source size/checksum/media verification"]
    if not cfg.model_api_key:
        report["blockers"].append({"code": "E_CREDENTIALS", "message": "MODEL_API_KEY is not configured in local .env"})
    if health["inference_mode"] != "live":
        report["blockers"].append({"code": "E_INFERENCE_MODE", "message": "API is in fixture mode; no processing was submitted"})
    if report["blockers"]:
        report.update(status="blocked", real_model_calls=0)
        save()
        print(json.dumps(report, indent=2))
        return
    # The existing server-side request budget is frozen into the job; default 16.
    submitted = call("POST", f"/v1/videos/{video_id}/process", json={"idempotency_key": args.idempotency_key})
    assert submitted["inference_mode"] == "live", "Refuse fixture inference"
    report.update(job_id=submitted["job_id"], run_id=submitted["run_id"], live_inference_submitted=True, status="running")
    save()
    started = time.monotonic()
    while time.monotonic()-started < 1200:
        job = call("GET", f"/v1/jobs/{submitted['job_id']}")
        if job["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    report.update(job_status=job["status"], elapsed_s=round(time.monotonic()-started, 3),
        model_runs=[{"model": r["model"], "status": r["status"], "request_id": r.get("request_id"),
            "usage": r.get("usage"), "latency_ms": r.get("latency_ms"), "error": r.get("error")} for r in job["model_runs"]])
    report["real_model_calls"] = len([r for r in job["model_runs"] if r["model"] != "files-api"])
    if job["status"] not in ("COMPLETED", "NEEDS_REVIEW"):
        report.update(status="failed" if job["status"] in ("FAILED", "CANCELLED") else "timed_out", error=job.get("error"))
        save()
        print(json.dumps(report, indent=2))
        return
    suffix = f"?run_id={job['run_id']}"
    plan = SemanticPlan.model_validate(call("GET", f"/v1/videos/{video_id}/actions{suffix}"))
    handoff = LayerOneHandoffManifest.model_validate(call("GET", f"/v1/videos/{video_id}/handoff{suffix}"))
    files = call("GET", f"/v1/videos/{video_id}/artifacts{suffix}")["artifacts"]
    content = {}
    for artifact in files:
        result = client.get(artifact["url"])
        result.raise_for_status()
        assert hashlib.sha256(result.content).hexdigest() == artifact["sha256"]
        content[artifact["name"]] = result.content
    rows = pq.read_table(io.BytesIO(content["tracks.parquet"])).to_pylist()
    masks = {name: json.loads(gzip.decompress(value)) for name, value in content.items() if name.endswith(".json.gz")}
    decoded = 0
    for raw in rows:
        row = TrackFrame.model_validate(raw)
        if row.mask_ref:
            key, fragment = row.mask_ref.split("#", 1)
            decode_rle(masks[Path(key).name][fragment])
            decoded += 1
    report.update(status="passed_with_review" if handoff.review_reasons else "passed", task=plan.task,
        entities=[e.entity_id for e in plan.entities], action_count=len(plan.actions), track_rows=len(rows),
        decoded_masks=decoded, artifact_count=len(files), review_reasons=handoff.review_reasons,
        ready_for_geometry=handoff.ready_for_geometry, accuracy_metrics="not_evaluated: independent annotations required",
        phase2_status="not_run: configured GPU runtime and local checkpoints required")
    report["checks"] += ["live semantic contract", "live track contracts", "mask decoding", "artifact SHA-256"]
    save()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Live baseline acceptance controller. Missing mandatory stages exit nonzero."""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--phase1-report", default="eval/reports/baseline-phase1-live.json")
    parser.add_argument("--robot-config", type=Path, help="JSON RobotizationConfig; required to execute Phase 3")
    parser.add_argument("--report", default="eval/reports/baseline-live.json")
    parser.add_argument("--body-backend", choices=["none", "sam3d"], default="sam3d")
    parser.add_argument("--run-perception", action="store_true", help="Explicitly spend bounded live inference calls")
    parser.add_argument("--low-vram", action="store_true", help="Four-frame 224px preview with CPU heads; not dense geometry")
    parser.add_argument("--idempotency-key", default="baseline-2026-11-03")
    args = parser.parse_args()
    from workers.pipeline import code_hash
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    result = {"status": "incomplete", "phases": {}, "blockers": [], "accepted": False,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(), "git_head": head.stdout.strip(),
        "code_hash": code_hash(), "independent_checks": {}}
    for name, filename in {"phase2_fixture": "phase2-reverification.json", "phase3_diagnostic": "phase3-smoke.json",
        "phase3_api_fixture": "phase3-api-smoke.json", "phase3_container": "phase3-container-smoke.json",
        "phase3_queue_fixture": "phase3-queue-smoke.json", "ablations_fixture": "baseline-ablations.json", "runtime": "runtime-preflight.json",
        "worker_runtime": "runtime-worker-preflight.json", "additional_source": "additional-source.json", "model_capabilities": "model-capabilities.json",
        "geometry_configured": "geometry-configured.json", "geometry_models_live": "live-geometry-models.json",
        "geometry_queue_live": "live-phase2-geometry.json"}.items():
        path = Path("eval/reports") / filename
        if path.is_file(): result["independent_checks"][name] = json.loads(path.read_text())
    result["independent_checks_note"] = "These software/fixture checks do not form a single real-video lineage and cannot satisfy live acceptance"
    target = Path(args.report)
    def save():
        def sanitized(value):
            if isinstance(value, dict): return {k: sanitized(v) for k,v in value.items()}
            if isinstance(value, list): return [sanitized(v) for v in value]
            if isinstance(value, str):
                return value.replace(str(Path.cwd())+"\\", "").replace(str(Path.cwd())+"/", "")
            return value
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(sanitized(result), indent=2), encoding="utf-8")
    client = httpx.Client(base_url=args.api, timeout=120)
    def call(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        if not r.is_success:
            try: data = r.json()
            except ValueError: data = {"message": r.text[:500]}
            raise RuntimeError(json.dumps({"http": r.status_code, **data}))
        return r.json()
    def wait(job):
        deadline = time.monotonic()+2400
        while time.monotonic() < deadline:
            current = call("GET", f"/v1/jobs/{job['job_id']}")
            if current["status"] in ("COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"):
                if current["status"] in ("FAILED", "CANCELLED"): raise RuntimeError(json.dumps(current.get("error")))
                return current
            time.sleep(2)
        raise RuntimeError("Pipeline timed out")
    try:
        if call("GET", "/health/ready")["inference_mode"] != "live":
            raise RuntimeError("Live acceptance refuses fixture API")
        if args.run_perception:
            subprocess.run([sys.executable, "-m", "scripts.live_smoke", "--api", args.api,
                "--report", args.phase1_report, "--idempotency-key", args.idempotency_key], check=True)
        source = json.loads(Path(args.phase1_report).read_text())
        if source["status"] not in ("passed", "passed_with_review") or not source.get("live_inference_submitted"):
            raise RuntimeError("Need a completed real perception report, or use --run-perception")
        result["phases"]["perception"] = source
        video_id = source["video_id"]
        queued = call("POST", f"/v1/videos/{video_id}/reconstruct", json={"source_job_id": source["job_id"],
            "idempotency_key": args.idempotency_key, "allow_review_source": True,
            "config": {"backend": "vggt", "body_backend": args.body_backend,
                **({"memory_mode": "low_vram", "image_size": 224, "max_total_frames": 4, "max_frames_per_shot": 4}
                   if args.low_vram else {"max_total_frames": 16, "max_frames_per_shot": 16})}})
        reconstructed = wait(queued)
        result["phases"]["reconstruction"] = reconstructed
        if args.robot_config is None:
            raise RuntimeError("Supply --robot-config with selected hand/object/shot/interval; automatic metric dimensions are not assumed")
        config = json.loads(args.robot_config.read_text())
        queued = call("POST", f"/v1/videos/{video_id}/robotize", json={"source_job_id": reconstructed["job_id"],
            "idempotency_key": args.idempotency_key, "allow_review_source": True, "config": config})
        robot = wait(queued)
        quality = call("GET", f"/v1/videos/{video_id}/robot-quality?run_id={robot['run_id']}")
        handoff = call("GET", f"/v1/videos/{video_id}/phase3-handoff?run_id={robot['run_id']}")
        result["phases"]["robotization"] = {"job": robot, "quality": quality, "handoff": handoff}
        result["accepted"] = quality["classification"] == "Gold" and all(v is True for v in quality["checks"].values())
        result["status"] = "passed" if result["accepted"] else "needs_review"
    except Exception as exc:
        result["blockers"].append(str(exc))
    finally:
        save()
    print(json.dumps({"status": result["status"], "blockers": result["blockers"], "report": args.report}))
    if not result["accepted"]: raise SystemExit(1)


if __name__ == "__main__":
    main()

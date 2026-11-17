"""Real footage through the queued stack: perception run -> identities -> 3D -> skill replication.

Starts from a finished live perception report (``scripts.live_smoke``). Every step is
an HTTP request to the running API and is executed by the queued worker. Steps
already recorded in the report are reused, so the script can be rerun after a failure.
Hosted model calls happen only in the perception step, which this script does not run.

    python -m scripts.real_video_replication --phase1 eval/reports/real-skill/close-laptop-phase1.json \
        --name close-laptop --start 0.6 --end 5.0
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

FINISHED = ("COMPLETED", "NEEDS_REVIEW")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase1", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--api", default="http://localhost:58000")
    parser.add_argument("--start", type=float, help="Reconstruction interval start (source seconds); default: around the plan's manipulation actions")
    parser.add_argument("--end", type=float)
    parser.add_argument("--associate", help="Reviewed identities when the heuristic abstains: entity=candidate@frame,... (recorded as assistant-reviewed)")
    parser.add_argument("--sample-fps", type=float, default=5)
    parser.add_argument("--max-frames", type=int, default=32)
    parser.add_argument("--no-body", action="store_true", help="Skip SAM 3D Body (no anatomical wrists, no body-derived scale)")
    parser.add_argument("--robot", default="panda")
    parser.add_argument("--hand"); parser.add_argument("--object")
    parser.add_argument("--template", default="auto"); parser.add_argument("--direction", default="auto")
    parser.add_argument("--version", default="v1", help="Changes idempotency keys to force new reconstruction/robotization runs")
    parser.add_argument("--robot-version", default="", help="Changes only the robotization key, reusing the reconstruction")
    parser.add_argument("--stop-after", choices=["associate", "reconstruct", "robotize"], default="robotize")
    args = parser.parse_args()
    phase1 = json.loads(args.phase1.read_text())
    if phase1.get("api_inference_mode") != "live" or phase1.get("job_status") not in FINISHED:
        raise SystemExit("A finished live perception report is required")
    video = phase1["video_id"]
    target = Path("eval/reports/real-skill")/f"{args.name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(target.read_text()) if target.exists() else {}
    if report.get("video_id") not in (None, video):
        report = {}
    report.update(name=args.name, video_id=video, source=phase1.get("source"), source_sha256=phase1.get("source_sha256"),
        perception={k: phase1.get(k) for k in ("job_id", "run_id", "task", "entities", "action_count", "real_model_calls", "review_reasons")})
    client = httpx.Client(base_url=args.api, timeout=300)

    def save():
        target.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")

    def call(method, path, **kwargs):
        # The API may restart while a queued job keeps running; polling should survive that.
        for attempt in range(6):
            try:
                response = client.request(method, path, **kwargs)
                break
            except httpx.TransportError:
                if attempt == 5:
                    raise
                time.sleep(5)
        if not response.is_success:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:600]}")
        return response.json()

    def wait(job, limit=3600):
        started = time.monotonic()
        while time.monotonic()-started < limit:
            detail = call("GET", f"/v1/jobs/{job['job_id']}")
            if detail["status"] in (*FINISHED, "FAILED", "CANCELLED"):
                return detail, round(time.monotonic()-started, 1)
            time.sleep(3)
        raise TimeoutError(f"{job['job_id']} did not finish in {limit}s")

    if call("GET", "/health/ready")["inference_mode"] != "live":
        raise SystemExit("API is not in live mode")

    # 1. Identities. Applies only what the motion-role heuristic can separate.
    source_job = phase1["job_id"]
    if "association" not in report:
        proposals = call("GET", f"/v1/videos/{video}/association-proposals", params={"source_job_id": source_job})
        entry = {"proposals": proposals["proposals"], "unresolved": proposals["reasons"], "method": proposals["method"]}
        if not proposals["proposals"] and args.associate:
            # One reviewed correction per run, chained; stored masks are reused, no hosted calls.
            entry["reviewed"] = args.associate
            for item in args.associate.split(","):
                entity, rest = item.split("=")
                candidate, frame = rest.split("@")
                job = call("POST", f"/v1/videos/{video}/corrections", json={"source_job_id": source_job, "entity_id": entity, "shot_id": "shot_000",
                    "frame_index": int(frame), "kind": "association", "provider_track_id": candidate, "reviewed_by": "assistant",
                    "evidence": "Candidate boxes reviewed on rendered frames of the normalized clip"})
                detail, elapsed = wait(job)
                entry.update(job_id=job["job_id"], run_id=job["run_id"], status=detail["status"], elapsed_s=elapsed, error=detail.get("error"))
                if detail["status"] not in FINISHED:
                    report["association"] = entry; save()
                    raise SystemExit(json.dumps(entry))
                source_job = job["job_id"]
        elif proposals["proposals"]:
            job = call("POST", f"/v1/videos/{video}/auto-associate", params={"source_job_id": source_job})
            detail, elapsed = wait(job)
            entry.update(job_id=job["job_id"], run_id=job["run_id"], status=detail["status"], elapsed_s=elapsed, error=detail.get("error"),
                hosted_model_calls=sum(r["model"] != "files-api" and r.get("status") == "completed" for r in detail.get("model_runs", [])))
            if detail["status"] not in FINISHED:
                report["association"] = entry; save()
                raise SystemExit(json.dumps(entry))
        report["association"] = entry
        save()
    source_job = report["association"].get("job_id", source_job)
    if args.stop_after == "associate":
        print(json.dumps(report["association"], indent=2)); return

    # 2. Geometry and contact evidence over the manipulation interval.
    if args.start is None or args.end is None:
        plan = call("GET", f"/v1/videos/{video}/actions", params={"run_id": phase1["run_id"]})
        acting = [a for a in plan["actions"] if a["primitive"] in ("OPEN", "CLOSE", "PULL", "PUSH", "LIFT", "TRANSPORT", "PLACE", "GRASP", "RELEASE", "ROTATE", "INSERT")]
        if not acting:
            raise SystemExit("The plan has no manipulation action; pass --start and --end")
        first = min(a["start_s"] for a in acting)
        args.start, args.end = max(0., first-1.2), min(plan["duration_s"], max(a["end_s"] for a in acting)+.8, first+5.5)
        report["interval"] = {"start_s": args.start, "end_s": args.end, "source": "semantic plan manipulation actions with margins"}
    key = f"real-skill-{args.name}-{args.version}"
    if report.get("reconstruction", {}).get("key") != key or report["reconstruction"].get("status") not in FINISHED:
        config = {"backend": "vggt", "body_backend": "none" if args.no_body else "sam3d", "memory_mode": "low_vram", "image_size": 224,
            "windowed": True, "start_s": args.start, "end_s": args.end, "sample_fps": args.sample_fps,
            "max_frames_per_shot": args.max_frames, "max_total_frames": args.max_frames}
        job = call("POST", f"/v1/videos/{video}/reconstruct", json={"source_job_id": source_job, "idempotency_key": key,
            "allow_review_source": True, "config": config})
        report["reconstruction"] = {"key": key, "job_id": job["job_id"], "run_id": job["run_id"], "config": config, "status": "running"}
        save()
        detail, elapsed = wait(job)
        report["reconstruction"].update(status=detail["status"], elapsed_s=elapsed, error=detail.get("error"))
        if detail["status"] in FINISHED:
            geometry = call("GET", f"/v1/videos/{video}/geometry-report", params={"run_id": job["run_id"]})
            report["reconstruction"]["geometry"] = {k: geometry.get(k) for k in ("camera_frames", "hand_pose_frames", "object_pose_frames",
                "relative_pose_frames", "contact_frames", "contact_events", "reprojection_median_px", "review_reasons")}
        save()
        if detail["status"] not in FINISHED:
            raise SystemExit(json.dumps(report["reconstruction"]))
    reconstruction = report["reconstruction"]
    if args.stop_after == "reconstruct":
        print(json.dumps(reconstruction, indent=2)); return

    # 3. Skill inference and replication, queued like any other Phase 3 job.
    proposal = call("GET", f"/v1/videos/{video}/robotize/proposal", params={"source_job_id": reconstruction["job_id"], "robot_id": args.robot,
        "mode": "skill", **({"hand_id": args.hand} if args.hand else {}), **({"object_id": args.object} if args.object else {})})
    report["proposal"] = {k: proposal.get(k) for k in ("available", "reasons", "paired_samples")}
    if not proposal["available"]:
        save()
        raise SystemExit(json.dumps(report["proposal"], indent=2))
    config = proposal["config"]
    config["replication"].update(template=args.template, direction=args.direction)
    payload = {"source_job_id": reconstruction["job_id"], "idempotency_key": key+"-robot"+args.robot_version, "allow_review_source": True, "config": config}
    check = call("POST", f"/v1/videos/{video}/robotize/check", json=payload)
    report["check"] = {k: check.get(k) for k in ("ready_for_ik_attempt", "reasons")}
    job = call("POST", f"/v1/videos/{video}/robotize", json=payload)
    detail, elapsed = wait(job)
    report["robotization"] = {"job_id": job["job_id"], "run_id": job["run_id"], "status": detail["status"], "elapsed_s": elapsed, "error": detail.get("error")}
    save()
    if detail["status"] not in FINISHED:
        raise SystemExit(json.dumps(report["robotization"], indent=2))
    output = Path("data/real-skill")/args.name
    (output/"simulation").mkdir(parents=True, exist_ok=True)
    artifacts = call("GET", f"/v1/videos/{video}/artifacts", params={"run_id": job["run_id"]})["artifacts"]
    wanted = {"replication_report.json", "quality_report.json", "simulation_report.json", "skill_model.json", "robot_trajectory.json",
              "simulation/simulation_replay.mp4", "learning_bundle.zip", "rl/rl_report.json", "export_report.json"}
    verified = 0
    for artifact in artifacts:
        if artifact["name"] not in wanted:
            continue
        content = client.get(artifact["url"]).content
        if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            raise SystemExit(f"Hash mismatch for {artifact['name']}")
        path = output/artifact["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        verified += 1
    replication = json.loads((output/"replication_report.json").read_text())
    simulation = json.loads((output/"simulation_report.json").read_text())
    quality = json.loads((output/"quality_report.json").read_text())
    from scripts.replicate_demo import viewer
    viewer(output, f"Replication from real footage: {replication['skill']['object_id']} ({args.name})", False)
    skill = replication["skill"]
    report["result"] = {"simulation_task_success": replication["simulation_task_success"],
        "skill": {k: skill[k] for k in ("kind", "template", "direction", "displacement", "displacement_unit", "confidence", "samples", "contact_samples", "direction_evidence")},
        "metric_scale": replication.get("metric_scale"), "scene": replication.get("scene") or replication.get("transport"),
        "replicated_displacement": replication["replicated_displacement"], "violations": simulation["violations"],
        "variations": [v["success"] for v in replication["variations"]], "quality": quality["classification"],
        "quality_reasons": quality["reasons"], "video": simulation.get("video"), "artifacts_verified": verified,
        "viewer": (output/"viewer.html").as_posix(), "review_reasons": replication["review_reasons"]}
    save()
    print(json.dumps(report["result"], indent=2))


if __name__ == "__main__":
    main()

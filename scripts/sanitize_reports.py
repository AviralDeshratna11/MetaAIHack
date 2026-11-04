"""Sanitize only the small checked-in acceptance summaries; never export raw data."""
import json
import subprocess
from pathlib import Path

from packages.common.config import settings

REPORTS = ["baseline-phase1-live.json", "phase2-reverification.json", "phase3-smoke.json", "phase3-api-smoke.json",
           "baseline-ablations.json", "runtime-preflight.json", "runtime-worker-preflight.json", "baseline-live.json",
           "phase3-container-smoke.json", "phase3-queue-smoke.json", "additional-source.json", "model-capabilities.json",
           "live-vggt.json", "geometry-configured.json", "live-geometry-models.json", "live-phase2-geometry.json",
           "learning-smoke.json", "pouring-repair.json", "live-learning.json", "learning-ablations.json", "robot-learning-acceptance.json", "fresh-provider-probe.json"]


def main():
    root = Path.cwd()
    def clean(value):
        if isinstance(value, dict): return {k: clean(v) for k,v in value.items()}
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, str):
            value = value.replace(str(root)+"\\", "").replace(str(root)+"/", "")
            if value.startswith(("data\\", "eval\\")): value = value.replace("\\", "/")
            return value
        return value
    for name in REPORTS:
        path = Path("eval/reports")/name
        if not path.is_file(): continue
        data = json.loads(path.read_text())
        if name == "baseline-phase1-live.json":
            calls = data.get("model_runs", [])
            data["completed_inference_calls"] = sum(r["status"] == "completed" and r["model"] != "files-api" for r in calls)
            data["failed_inference_attempts"] = sum(r["status"] == "failed" and r["model"] != "files-api" for r in calls)
            data["actual_cost_usd"] = None
        path.write_text(json.dumps(clean(data), indent=2)+"\n", encoding="utf-8")
    # Scan the exact current credential in tracked/unignored files without printing it.
    key = settings().model_api_key
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture_output=True, check=True).stdout.split(b"\0")
    failures = []
    for raw in files:
        if not raw: continue
        path = Path(raw.decode())
        if key and path.is_file() and key.encode() in path.read_bytes(): failures.append(path.as_posix())
    if failures: raise SystemExit("Credential detected in publishable files: "+", ".join(failures))
    print(json.dumps({"reports_sanitized": len(REPORTS), "credential_matches": len(failures)}))


if __name__ == "__main__":
    main()

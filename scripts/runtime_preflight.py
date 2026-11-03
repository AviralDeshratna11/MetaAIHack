"""Sanitized runtime capability inventory; never prints credential values."""
import importlib.metadata
import importlib.util
import argparse
import json
import subprocess
from pathlib import Path

from packages.common.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="eval/reports/runtime-preflight.json")
    parser.add_argument("--label", default="native-project-environment")
    args = parser.parse_args()
    cfg = settings()
    report = {"environment": args.label, "host_packages": {}, "model_key_configured": bool(cfg.model_api_key),
        "geometry_python_configured": bool(cfg.geometry_python), "lerobot_python_configured": bool(cfg.lerobot_python),
        "local_dataset_environment_detected": any(p.is_file() for p in (Path(".venv-lerobot/Scripts/python.exe"), Path(".venv-lerobot/bin/python"))),
        "checkpoints": {name: bool(value and Path(value).is_file()) for name, value in {
            "vggt": cfg.vggt_checkpoint, "sam3d_body": cfg.sam3d_body_checkpoint, "mhr": cfg.sam3d_mhr_path}.items()},
        "robot_assets_present": (Path(cfg.robot_assets)/"asset_manifest.json").is_file()}
    for package in ("torch", "mujoco", "scipy", "lerobot", "vggt", "sam_3d_body"):
        if importlib.util.find_spec(package) is None:
            report["host_packages"][package] = None
        else:
            try: report["host_packages"][package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: report["host_packages"][package] = "importable; metadata unavailable"
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        report["gpu"] = p.stdout.strip() if p.returncode == 0 else "unavailable"
    except (FileNotFoundError, subprocess.TimeoutExpired): report["gpu"] = "unavailable"
    report["live_geometry_ready"] = bool(cfg.geometry_python) and all(report["checkpoints"].values())
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

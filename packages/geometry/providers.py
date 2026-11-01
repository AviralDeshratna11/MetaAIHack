"""CPU fixture and an isolated local-GPU process using preinstalled official models."""
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from packages.common.utils import DomainError, file_hash
from packages.geometry.math3d import unproject


def provider_fingerprint(config):
    if config["backend"] == "fixture":
        return {"model": "synthetic-relative-scene-v1"}
    result = {"model": "vggt-local", "body": config["body_backend"]}
    for name in ("vggt_checkpoint", "body_checkpoint", "body_mhr"):
        path = config.get(name)
        if path:
            if not Path(path).is_file():
                raise DomainError("E_GEOMETRY_CHECKPOINT", f"Configured {name} file is unavailable", 503)
            result[name] = file_hash(Path(path))
    if not config.get("vggt_checkpoint") or not config.get("gpu_python"):
        raise DomainError("E_GEOMETRY_CONFIG", "Configure GEOMETRY_PYTHON and VGGT_CHECKPOINT for live reconstruction", 503)
    if config["body_backend"] == "sam3d" and not all(config.get(k) for k in ("body_checkpoint", "body_mhr")):
        raise DomainError("E_GEOMETRY_CONFIG", "SAM3D_BODY_CHECKPOINT and SAM3D_MHR_PATH are required for body inference", 503)
    return result


class FixtureGeometry:
    name = "synthetic-relative-scene-v1"

    def reconstruct(self, frames, manifest, output, config):
        # Deliberately synthetic pinhole scene, never called for live footage.
        w, h = manifest.width, manifest.height
        k = np.array([[w, 0, w/2], [0, w, h/2], [0, 0, 1.]], float)
        result = {}
        for index in frames:
            y, x = np.indices((h, w))
            depth = 1 + .015 * np.sin(x / max(w, 1) * np.pi) + .01 * y / max(h, 1)
            result[index] = {"intrinsic": k, "world_from_camera": np.eye(4),
                "points": unproject(depth, k, np.eye(4)), "confidence": np.ones((h, w)), "body": []}
        return result


class LocalGeometry:
    name = "vggt-local"

    def reconstruct(self, frames, manifest, output, config):
        request = output / "gpu_request.json"
        request.write_text(json.dumps({"frames": {str(k): str(v.resolve()) for k, v in frames.items()},
            "width": manifest.width, "height": manifest.height, "config": config}), encoding="utf-8")
        try:
            completed = subprocess.run([config["gpu_python"], "-m", "workers.geometry.gpu_entry",
                "--request", str(request), "--output", str(output)], capture_output=True, timeout=config.get("timeout", 900),
                env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise DomainError("E_GEOMETRY_RUNTIME", "GPU Python unavailable or reconstruction timed out", 503) from exc
        (output / "gpu_stdout.log").write_bytes(completed.stdout)
        (output / "gpu_stderr.log").write_bytes(completed.stderr)
        if completed.returncode:
            raise DomainError("E_GEOMETRY_RUNTIME", "Local GPU inference failed; inspect GPU runtime configuration and worker logs", 503)
        result = {}
        for index in frames:
            with np.load(output / f"frame_{index}.npz", allow_pickle=False) as data:
                k, transform, points = data["intrinsic"], data["world_from_camera"], data["points"]
                if points.shape != (manifest.height, manifest.width, 3):
                    raise DomainError("E_GEOMETRY_CONTRACT", "GPU point-map resolution differs from normalized video")
                body = json.loads((output / f"body_{index}.json").read_text())
                result[index] = {"intrinsic": k, "world_from_camera": transform,
                    "points": points, "confidence": data["confidence"], "body": body}
        return result

"""Offline checkpoint/import/CUDA verification in the provisioned geometry runtime."""
import argparse
import importlib.metadata
import json
import platform
from pathlib import Path

from packages.common.utils import file_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, default=Path("/models"))
    parser.add_argument("--report", type=Path, default=Path("eval/reports/geometry-configured.json"))
    args = parser.parse_args()
    import torch
    import vggt
    import sam_3d_body
    if not torch.cuda.is_available(): raise RuntimeError("CUDA is not exposed to the runtime")
    manifests = {}
    for name in ("vggt", "body"):
        root = args.models/name
        manifest = json.loads((root/"checkpoint_manifest.json").read_text())
        for filename, info in manifest["files"].items():
            path = (root/filename).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != info["sha256"]:
                raise RuntimeError("Checkpoint integrity check failed")
        manifests[name] = manifest
    packages = {n: importlib.metadata.version(n) for n in ("torch", "torchvision", "numpy", "vggt", "pytorch-lightning", "timm", "accelerate")}
    report = {"status": "configured_and_integrity_verified", "python": platform.python_version(), "packages": packages,
        "body_version": sam_3d_body.__version__, "cuda_available": True, "gpu": torch.cuda.get_device_name(0),
        "gpu_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "checkpoints": manifests, "note": "Imports and file integrity are verified here; inference requires separate real output evidence"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "checkpoints"}))


if __name__ == "__main__":
    main()

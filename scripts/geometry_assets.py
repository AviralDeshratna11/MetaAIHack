"""Download pinned official geometry weights; Hugging Face credentials stay local."""
import argparse
import json
import os
import logging
import shutil
from pathlib import Path

from packages.common.utils import file_hash

MODELS = {
    "vggt": ("facebook/VGGT-1B", "860abec7937da0a4c03c41d3c269c366e82abdf9", ["model.pt", "config.json", "README.md"]),
    "body": ("facebook/sam-3d-body-dinov3", "11aaa346c7204874a1cbafe3d39a979080b2c55a", ["model.ckpt", "model_config.yaml", "assets/mhr_model.pt", "LICENSE", "README.md"]),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("--check-access", action="store_true")
    parser.add_argument("--output", type=Path, help="Authorized model-storage directory; defaults to data/models/MODEL")
    args = parser.parse_args()
    # Avoid native transfer acceleration; standard HTTPS supports this environment.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    logging.getLogger("huggingface_hub").setLevel(logging.CRITICAL)
    logging.disable(logging.CRITICAL)
    from huggingface_hub import HfApi, get_token, get_hf_file_metadata, hf_hub_url, hf_hub_download
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
    repo, revision, names = MODELS[args.model]
    token = get_token()
    try:
        metadata = get_hf_file_metadata(hf_hub_url(repo, names[0], revision=revision), token=token)
    except GatedRepoError:
        print(json.dumps({"status": "access_required", "repo": repo, "url": "https://huggingface.co/"+repo}))
        raise SystemExit(2)
    except HfHubHTTPError as exc:
        print(json.dumps({"status": "http_error", "http": exc.response.status_code if exc.response is not None else None, "repo": repo}))
        raise SystemExit(2)
    if args.check_access:
        print(json.dumps({"status": "download_permitted", "repo": repo, "revision": revision, "checkpoint_bytes": metadata.size}))
        return
    root = args.output or Path("data/models") / args.model
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    info = HfApi(token=token).model_info(repo, revision=revision, files_metadata=True)
    upstream = {f.rfilename: f for f in info.siblings}
    needed = sum(upstream[name].size for name in names if not (root/name).is_file())
    free = shutil.disk_usage(root).free
    if free < needed+1024**3:
        print(json.dumps({"status": "insufficient_disk", "required_bytes_with_reserve": needed+1024**3, "free_bytes": free}))
        raise SystemExit(3)
    for name in names:
        print(json.dumps({"downloading": name, "repo": repo}), flush=True)
        target = Path(hf_hub_download(repo, name, revision=revision, token=token, local_dir=root))
        digest = file_hash(target)
        entry = upstream[name]
        expected = entry.lfs.sha256 if entry.lfs else None
        if entry.size != target.stat().st_size or expected and expected != digest:
            raise RuntimeError("Downloaded checkpoint checksum/length mismatch")
        files[name] = {"sha256": digest, "bytes": target.stat().st_size, "upstream_lfs_sha256": expected}
    (root / "checkpoint_manifest.json").write_text(json.dumps({"repo": repo, "revision": revision, "files": files}, indent=2), encoding="utf-8")
    print(json.dumps({"status": "verified", "model": args.model, "directory": root.as_posix()}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exceptions may contain signed URLs. Never print those URLs/tokens.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "message": "Model transfer failed; rerun to resume; no unverified checkpoint is activated"}))
        raise SystemExit(1)

"""Download the official Apache-2.0 Panda assets at an immutable upstream commit."""
import argparse
import json
import urllib.request
from pathlib import Path

from packages.common.utils import file_hash


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Video2Robot-baseline"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="main", help="Resolved to an immutable commit before any asset download")
    parser.add_argument("--output", default="data/robots/franka_emika_panda")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    api = "https://api.github.com/repos/google-deepmind/mujoco_menagerie"
    commit = json.loads(fetch(f"{api}/commits/{args.revision}"))["sha"]
    tree = json.loads(fetch(f"{api}/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise RuntimeError("Asset inventory truncated")
    files = {}
    for entry in tree["tree"]:
        prefix = "franka_emika_panda/"
        if entry["type"] != "blob" or not entry["path"].startswith(prefix):
            continue
        relative = entry["path"][len(prefix):]
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("Invalid asset path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(f"https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/{commit}/{entry['path']}"))
        files[relative] = file_hash(path)
    manifest = {"repository": "https://github.com/google-deepmind/mujoco_menagerie", "commit": commit,
                "license": "Apache-2.0", "files": files}
    (root / "asset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"commit": commit, "files": len(files), "output": root.as_posix()}))


if __name__ == "__main__":
    main()

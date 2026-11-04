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
    parser.add_argument("--revision", default="98a70c569c4c1b6da467a20012f766ee1f8dc521", help="Pinned tested Menagerie revision; overrides resolve before download")
    parser.add_argument("--output", default=None)
    parser.add_argument("--robot",choices=["panda","fr3"],default="panda")
    args = parser.parse_args()
    root = Path(args.output or ('data/robots/franka_emika_panda' if args.robot=='panda' else 'data/robots/franka_fr3'))
    root.mkdir(parents=True, exist_ok=True)
    api = "https://api.github.com/repos/google-deepmind/mujoco_menagerie"
    commit = json.loads(fetch(f"{api}/commits/{args.revision}"))["sha"]
    tree = json.loads(fetch(f"{api}/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise RuntimeError("Asset inventory truncated")
    files = {}
    for entry in tree["tree"]:
        prefix = "franka_emika_panda/" if args.robot == "panda" else "franka_fr3/"
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
                "license": "Apache-2.0", "files": files,"robot":args.robot}
    if args.robot == "fr3":
        from packages.robot.fr3 import compose_hand
        compose_hand(root,Path('data/robots/franka_emika_panda'))
        manifest['gripper_source']=json.loads(Path('data/robots/franka_emika_panda/asset_manifest.json').read_text())
        manifest['composition']='Official FR3 arm plus official Panda parallel gripper; simulated flange attachment, not physically certified'
        manifest['files']={p.relative_to(root).as_posix():file_hash(p) for p in root.rglob('*') if p.is_file() and p.name!='asset_manifest.json'}
    (root / "asset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"commit": commit, "files": len(files), "output": root.as_posix()}))


if __name__ == "__main__":
    main()

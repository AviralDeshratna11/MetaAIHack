"""Pin the public DINOv3 source needed by the offline body constructor."""
import argparse
import hashlib
import io
import json
import time
import urllib.request
import zipfile
from pathlib import Path

SOURCES = {
    "dinov3": ("facebookresearch/dinov3", "6876159a11b4df116f30f667f8c9888617df0751"),
    "vggt": ("facebookresearch/vggt", "a288dd0f14786c93483e45524328726ab7b1b4ce"),
    "body": ("facebookresearch/sam-3d-body", "b5c765a0d89d789985e186d396315e7590887b94"),
}


def fetch(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Video2Robot-model-setup"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 3: raise
            time.sleep(2**attempt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, default=Path("/models"))
    parser.add_argument("--component", choices=SOURCES, default="dinov3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo, revision = SOURCES[args.component]
    target = args.output or (args.models/"sources"/"dinov3" if args.component == "dinov3"
        else Path("data/vendor") / (repo.split("/")[-1]+"-"+revision))
    base = target.parent
    base.mkdir(parents=True, exist_ok=True)
    if (target/"source_manifest.json").is_file():
        print((target/"source_manifest.json").read_text()); return
    if target.exists(): raise RuntimeError("Unverified existing source directory; preserve it for inspection")
    archive = fetch("https://codeload.github.com/"+repo+"/zip/"+revision)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if not all((base/n).resolve().is_relative_to(base.resolve()) for n in z.namelist()):
            raise RuntimeError("Invalid source archive path")
        root = base / z.namelist()[0].split("/")[0]
        z.extractall(base)
    if root != target and target.exists(): raise RuntimeError("Unverified existing source directory; preserve it for inspection")
    if not root.resolve().is_relative_to(base.resolve()) or not target.resolve().is_relative_to(base.resolve()):
        raise RuntimeError("Source directory escaped model storage")
    if root != target:
        root.rename(target)
    report = {"repo": "https://github.com/"+repo, "revision": revision,
              "archive_sha256": hashlib.sha256(archive).hexdigest()}
    (target/"source_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

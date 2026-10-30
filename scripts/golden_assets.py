import argparse
import json
import shutil
from pathlib import Path

from packages.common.utils import file_hash
from packages.video.processing import probe

MANIFEST = Path("eval/golden/manifest.json")


def main():
    parser = argparse.ArgumentParser(description="Import authorized real golden media or validate missing assets")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("validate")
    imp = sub.add_parser("import")
    imp.add_argument("scenario")
    imp.add_argument("path", type=Path)
    imp.add_argument("--rights", required=True, choices=["team_recorded", "licensed", "user_supplied"])
    imp.add_argument("--source", required=True)
    imp.add_argument("--license", default="not_specified")
    imp.add_argument("--consent", default="not_specified")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text())
    if args.action == "import":
        match = next((c for c in data["clips"] if c["scenario"] == args.scenario), None)
        if match is None:
            raise SystemExit("Unknown scenario; add it to the manifest first")
        metadata = probe(args.path)
        target = Path("data/golden") / f"{args.scenario}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise SystemExit("Target already exists; import under a new scenario/version")
        shutil.copyfile(args.path, target)
        match.update(status="available", path=target.as_posix(), sha256=file_hash(target),
                     duration_s=metadata["duration_s"], source_uri=args.source,
                     rights_status=args.rights, license=args.license, consent=args.consent)
        MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    failures = []
    for clip in data["clips"]:
        if clip["status"] == "missing_source":
            print(f"MISSING: {clip['scenario']}")
        elif not Path(clip["path"]).is_file() or file_hash(Path(clip["path"])) != clip["sha256"]:
            failures.append(clip["scenario"])
    if failures:
        raise SystemExit(f"Invalid source hashes: {failures}")
    print(f"Validated {len(data['clips'])} manifest entries; missing sources are explicitly unresolved, not passes.")


if __name__ == "__main__":
    main()

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from packages.common.config import settings
from packages.meta_client.fixture import fixture_plan
from packages.meta_client.fixture import FixtureProvider
from packages.common.utils import file_hash
from packages.schemas.models import LayerOneHandoffManifest
from packages.video.processing import normalize


def make_video(path: Path, seconds=12, fps=15):
    """Generated shapes, deliberately not a human demonstration or AI output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([settings().ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", "640x360", "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for index in range(seconds * fps):
            t = index / (seconds * fps)
            image = np.full((360, 640, 3), (31, 34, 32), dtype=np.uint8)
            cv2.rectangle(image, (30, 282), (610, 287), (74, 81, 76), -1)
            cv2.putText(image, "SYNTHETIC FIXTURE / NO MODEL INFERENCE", (24, 30), cv2.FONT_HERSHEY_SIMPLEX, .48, (180, 185, 180), 1)
            x = int(170 + 220 * np.sin(np.pi * t) ** 2)
            y = int(225 - 100 * np.sin(np.pi * t))
            cv2.rectangle(image, (x - 25, y - 30), (x + 25, y + 30), (40, 135, 245), -1)
            cv2.rectangle(image, (x + 25, y - 15), (x + 39, y + 13), (40, 135, 245), 6)
            cv2.ellipse(image, (450, 260), (62, 23), 0, 0, 180, (170, 190, 40), -1)
            cv2.ellipse(image, (x - 60, y), (28, 14), -20, 0, 360, (190, 100, 190), -1)
            proc.stdin.write(image.tobytes())
        proc.stdin.close()
        error = proc.stderr.read()
        if proc.wait(timeout=60):
            raise RuntimeError(error.decode(errors="replace"))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def main():
    plan = fixture_plan(12)
    root = Path("fixtures")
    root.mkdir(exist_ok=True)
    (root / "semantic_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    (root / "action_graph.json").write_text(plan.action_graph.model_dump_json(indent=2), encoding="utf-8")
    source = Path("data/synthetic-fixture.mp4")
    make_video(source)
    manifest = normalize(source, Path("data/fixture-normalized"), "fixture-video", 15)
    import pyarrow.parquet as pq
    from workers.perception.tracking import tracking
    class FixtureLog:
        mode = "fixture"
        last_id = "fixture-model-run"
        def __call__(self, event): pass
    perception = root / "perception"
    report = tracking(FixtureProvider(), Path("data/fixture-normalized/video_720p_15fps.mp4"), manifest,
        plan, pq.read_table("data/fixture-normalized/frame_map.parquet").to_pylist(), perception,
        "fixtures/perception", FixtureLog(), [])
    # Root-level fixture names match the frozen first-layer handoff examples.
    import shutil
    shutil.copyfile(perception / "tracks.parquet", root / "tracks.parquet")
    handoff = LayerOneHandoffManifest(video_id="fixture-video", run_id="fixture-static-v1", inference_mode="fixture",
        artifacts={"semantic_plan": "fixtures/semantic_plan.json", "action_graph": "fixtures/action_graph.json",
                   "tracks": "fixtures/tracks.parquet", "normalized_manifest": "data/fixture-normalized/manifest.json",
                   "tracking_report": "fixtures/perception/tracking_report.json",
                   **{name: f"fixtures/perception/{name}" for name in report["mask_bundles"]}},
        entities=[e.entity_id for e in plan.entities], ready_for_geometry=False,
        review_reasons=["Synthetic fixture: not real model inference or a human demonstration"])
    (root / "handoff_manifest.json").write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
    (root / "source.json").write_text(json.dumps({"synthetic": True, "source": source.as_posix(),
        "sha256": file_hash(source), "duration_s": 12, "generator": "scripts.make_fixtures"}, indent=2), encoding="utf-8")
    print("Created synthetic media; not real-model evaluation evidence")


if __name__ == "__main__":
    main()

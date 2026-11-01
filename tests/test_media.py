import json
import shutil

import cv2
import numpy as np
import pyarrow.parquet as pq
import pytest

from packages.common.config import settings
from packages.video.processing import command, normalize, probe

pytestmark = pytest.mark.skipif(not shutil.which(settings().ffmpeg) or not shutil.which(settings().ffprobe),
    reason="FFmpeg/ffprobe required; these tests run inside the backend image")


def frames(path):
    cap = cv2.VideoCapture(str(path)); result = []
    while True:
        ok, frame = cap.read()
        if not ok: break
        result.append(frame)
    cap.release()
    return result


def test_vfr_mapping_matches_actual_ffmpeg_pixels(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "min_duration", .01)
    durations = [.08, .16, .12, .24, .08, .16]
    lines = []
    for index, duration in enumerate(durations):
        image = np.full((64, 96, 3), 20 + 30 * index, np.uint8)
        path = tmp_path / f"frame{index}.png"; cv2.imwrite(str(path), image)
        lines += [f"file '{path.as_posix()}'", f"duration {duration}"]
    lines += [f"file '{path.as_posix()}'"]
    listing = tmp_path / "frames.txt"; listing.write_text("\n".join(lines))
    source = tmp_path / "vfr.mp4"
    command([settings().ffmpeg, "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-vsync", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)])
    manifest = normalize(source, tmp_path / "output", "vfr", 15)
    mapping = pq.read_table(tmp_path / "output/frame_map.parquet").to_pylist()
    originals = frames(source); normalized = frames(tmp_path / "output/video_720p_15fps.mp4")
    assert len(mapping) == len(normalized) == manifest.frame_count
    for row, actual in zip(mapping, normalized):
        expected = originals[row["source_frame_index"]]
        assert abs(float(actual.mean()) - float(expected.mean())) < 4, (row, actual.mean(), expected.mean())


def test_rotation_nonzero_pts_and_no_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "min_duration", .01)
    source = tmp_path / "source.mp4"
    command([settings().ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=10:duration=1",
             "-c:v", "libx264", "-output_ts_offset", "5", "-y", str(source)])
    rotated = tmp_path / "rotated.mp4"
    command([settings().ffmpeg, "-v", "error", "-i", str(source), "-c", "copy", "-copyts",
             "-metadata:s:v:0", "rotate=90", "-y", str(rotated)])
    manifest = normalize(rotated, tmp_path / "out", "rotation", 15)
    assert manifest.width == 96 and manifest.height == 160
    assert not (tmp_path / "out/audio.wav").exists()
    assert not manifest.original["has_audio"]
    assert manifest.original["start_time"] >= 5
    mapping = pq.read_table(tmp_path / "out/frame_map.parquet").to_pylist()
    assert mapping[0]["timestamp"] == 0 and mapping[0]["source_timestamp"] >= 5


def test_real_media_tracking_survives_missing_masks_and_preserves_uncertainty(tmp_path, monkeypatch):
    from packages.meta_client.fixture import FixtureProvider, fixture_plan
    from workers.perception.tracking import tracking

    monkeypatch.setattr(settings(), "min_duration", .01)
    source = tmp_path / "occlusion.mp4"
    command([settings().ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:size=96x64:rate=15:duration=2",
        "-vf", "drawbox=x=20:y=20:w=20:h=20:color=0xf58728:t=fill:enable='not(between(n,7,9))'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)])
    normalized = tmp_path / "normalized"
    manifest = normalize(source, normalized, "occlusion", 15)
    mapping = pq.read_table(normalized / "frame_map.parquet").to_pylist()
    class Recorder:
        mode = "fixture"
        last_id = "synthetic-model-run"
        def __call__(self, event): pass
    output = tmp_path / "tracking"
    report = tracking(FixtureProvider(), normalized / manifest.normalized_ref, manifest,
        fixture_plan(manifest.duration_s), mapping, output, "fixture-prefix", Recorder(), [])
    rows = pq.read_table(output / "tracks.parquet").to_pylist()
    mug = [row for row in rows if row["entity_id"] == "mug"]
    assert len(mug) == manifest.frame_count == 30
    assert all(not row["observed"] and row["bbox_xyxy"] is None for row in mug[7:10])
    assert mug[10]["observed"] and mug[10]["identity_status"] == "unverified"
    assert mug[10]["track_id"] != mug[6]["track_id"]
    assert any("Unverified identity" in reason for reason in report["review_reasons"])

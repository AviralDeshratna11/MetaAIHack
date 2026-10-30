from pathlib import Path

import numpy as np

from packages.meta_client.fixture import fixture_plan
from packages.schemas.models import Shot, TrackFrame, VideoManifest
from workers.perception.tracking import build_tracklets


def setup():
    shot = Shot(shot_id="shot_000", start_frame=0, end_frame=8)
    manifest = VideoManifest(video_id="vid_test", original={}, normalized_ref="video.mp4", width=40, height=20,
        fps_num=15, frame_count=8, duration_s=8/15, normalization_hash="test", frame_map_ref="map", shots=[shot],
        keyframe_refs=[], diagnostics={})
    return shot, manifest, [{"source_timestamp": i/15} for i in range(8)]


def rec(frame, object_id="0"):
    mask = np.zeros((20, 40), np.uint8); mask[3:8, 10:15] = 1
    return {"frame": frame, "object_id": object_id, "mask": mask, "bbox": [10, 3, 15, 8], "confidence": None}


def build(records, correction=None):
    shot, manifest, frames = setup()
    return build_tracklets(records, fixture_plan(12).entities[1], shot, manifest, frames, "vid_test", "model_test", "mask.gz", correction)


def test_contiguous_provider_identity_and_nullable_confidence():
    rows, masks, summaries = build([rec(i) for i in range(8)])
    assert len({r["track_id"] for r in rows}) == 1
    assert all(r["provider_confidence"] is None for r in rows)
    assert all(TrackFrame.model_validate(r).observed for r in rows)
    assert rows[0]["bbox_xyxy"] == [10, 3, 15, 8]


def test_occluded_frames_have_no_hallucinated_masks_and_reappearance_is_unverified():
    rows, _, summaries = build([rec(0), rec(1), rec(5), rec(6)])
    assert not rows[3]["observed"] and rows[3]["mask_ref"] is None
    assert rows[5]["identity_status"] == "unverified"
    assert rows[5]["track_id"] != rows[0]["track_id"]


def test_two_candidates_are_ambiguous_until_explicit_association():
    records = [rec(i, candidate) for i in range(8) for candidate in ("0", "2")]
    rows, _, _ = build(records)
    assert all(r["identity_status"] == "ambiguous" for r in rows)
    resolved, _, _ = build(records, {"kind": "association", "provider_track_id": "2"})
    assert all(r["provider_track_id"] == "2" and r["identity_status"] == "associated" for r in resolved)


def test_shots_never_share_track_identity():
    shot, manifest, frames = setup()
    first, _, _ = build([rec(i) for i in range(8)])
    shot.shot_id = "shot_001"
    second, _, _ = build_tracklets([rec(i) for i in range(8)], fixture_plan(12).entities[1], shot,
        manifest, frames, "vid_test", "model_test", "mask2.gz")
    assert first[0]["track_id"] != second[0]["track_id"]

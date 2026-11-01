from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from packages.meta_client.fixture import fixture_plan
from packages.schemas.models import Shot, TrackFrame, VideoManifest
from workers.perception.tracking import build_tracklets, tracking


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


def test_empty_masks_do_not_start_reappearance_tracklets():
    empty = rec(5)
    empty["mask"][:] = 0
    rows, masks, _ = build([rec(0), empty, rec(7)])
    assert not rows[5]["observed"] and rows[5]["mask_ref"] is None
    assert rows[5]["track_id"] == rows[0]["track_id"]
    assert rows[7]["track_id"].endswith(":1")
    assert rows[7]["identity_status"] == "unverified"


def test_single_missing_frame_does_not_prove_reappearance_identity():
    rows, _, _ = build([rec(i) for i in range(8) if i != 2])
    assert rows[3]["track_id"] != rows[0]["track_id"]
    assert rows[3]["identity_status"] == "unverified"
    assert all(r["warnings"] for r in rows[3:])


def test_shared_concept_is_ambiguous_even_with_one_provider_candidate():
    shot, manifest, frames = setup()
    rows, _, _ = build_tracklets([rec(i) for i in range(8)], fixture_plan(12).entities[1], shot,
        manifest, frames, "vid_test", "model_test", "mask.gz", shared_concept=True)
    assert all(r["identity_status"] == "ambiguous" for r in rows)


@pytest.mark.parametrize("problem", ["reappearance", "motion", "shared_concept"])
def test_tracking_gate_blocks_unresolved_identity_and_geometry(problem, tmp_path, monkeypatch):
    shot, manifest, frame_map = setup()
    # A long clip lets a brief failure exceed the coverage gate, so the independent
    # identity/anomaly checks must still prevent ready_for_geometry.
    shot.end_frame = manifest.frame_count = 40
    manifest.duration_s = 40 / 15
    manifest.diagnostics = {"frames": []}
    frame_map = [{"source_timestamp": i / 15} for i in range(40)]
    plan = fixture_plan(manifest.duration_s)
    if problem == "shared_concept":
        second = plan.entities[1].model_copy(update={"entity_id": "second_mug"})
        plan.entities.append(second)
    monkeypatch.setattr("workers.perception.tracking.extract_shot", lambda video, dest, shot: dest.touch())
    class Provider:
        def track(self, *args):
            records = [rec(i) for i in range(40) if problem != "reappearance" or i != 38]
            if problem == "motion":
                records[20]["mask"][:] = 0
                records[20]["mask"][3:8, 30:35] = 1
            return records
    class Recorder:
        mode = "live"
        last_id = "model-test"
    report = tracking(Provider(), tmp_path / "video.mp4", manifest, plan, frame_map,
        tmp_path / "tracking", "prefix", Recorder(), [])
    expected = {"reappearance": "Unverified identity", "motion": "anomalies", "shared_concept": "Ambiguous"}[problem]
    assert any(expected in reason for reason in report["review_reasons"])
    saved = pq.read_table(tmp_path / "tracking/tracks.parquet").to_pylist()
    assert all(TrackFrame.model_validate(row) for row in saved)
    if problem == "reappearance":
        missing = [row for row in saved if row["frame_index"] == 38]
        assert len(missing) == 3
        assert all(row["bbox_xyxy"] is None and row["centroid"] is None for row in missing)

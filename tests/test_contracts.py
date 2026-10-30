import copy

import numpy as np
import pytest
from pydantic import ValidationError

from packages.meta_client.fixture import fixture_plan
from packages.schemas.models import ActionGraph, Edge, SemanticPlan, TrackFrame
from packages.video.masks import decode_rle, encode_rle
from packages.video.processing import source_mapping


@pytest.mark.parametrize("mutation", ["unknown_entity", "cycle", "out_of_duration", "nonfinite", "duplicate_entity", "extra"])
def test_semantic_contract_rejects_corrupt_data(mutation):
    data = fixture_plan(12).model_dump(mode="json")
    if mutation == "unknown_entity": data["actions"][0]["actor"] = "undeclared"
    if mutation == "cycle": data["action_graph"]["edges"].append({"source": "a06", "target": "a00", "reason": "temporal"})
    if mutation == "out_of_duration": data["actions"][0]["end_s"] = 99
    if mutation == "nonfinite": data["actions"][0]["start_s"] = float("nan")
    if mutation == "duplicate_entity": data["entities"].append(data["entities"][0])
    if mutation == "extra": data["robot_actions"] = []
    with pytest.raises(ValidationError): SemanticPlan.model_validate(data)


def test_overlap_and_partial_order_are_valid():
    data = fixture_plan(12).model_dump(mode="json")
    data["actions"][1]["start_s"] = .1
    data["action_graph"]["edges"] = []
    assert SemanticPlan.model_validate(data).actions[1].start_s == .1


@pytest.mark.parametrize("kind", ["zero", "one", "random"])
def test_mask_roundtrip(kind):
    mask = np.zeros((17, 31), dtype=np.uint8) if kind == "zero" else np.ones((17, 31), dtype=np.uint8)
    if kind == "random": mask = np.random.default_rng(47).integers(0, 2, (17, 31), dtype=np.uint8)
    assert np.array_equal(decode_rle(encode_rle(mask)), mask)


def test_bad_rle_rejected():
    with pytest.raises(ValueError): decode_rle({"encoding": "row-major-rle-v1", "width": 2, "height": 2, "counts": [5]})


def test_source_map_preserves_nonzero_pts_and_duplication():
    rows = source_mapping([10., 10.1, 10.3], 8, 20)
    assert rows[0]["source_timestamp"] == 10.
    assert rows[0]["timestamp"] == 0
    assert rows[1]["mapping"] == "duplicated"
    assert rows[6]["source_frame_index"] == 2
    assert all(a["source_timestamp"] <= b["source_timestamp"] for a, b in zip(rows, rows[1:]))


def test_source_map_accounts_for_dropped_frames():
    rows = source_mapping([i / 60 for i in range(60)], 15, 15)
    assert any(row["source_frames_dropped_before"] > 0 for row in rows)

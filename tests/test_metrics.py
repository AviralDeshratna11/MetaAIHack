from eval.metrics.evaluate import evaluate


def test_unknown_annotations_are_not_perfect_scores():
    result = evaluate({"video_id": "v", "actions": None, "selected_masks": None, "identity_frames": None}, {})
    assert all(value["status"] == "not_evaluated" for value in result["metrics"].values())


def test_temporal_matching_is_one_to_one():
    a = {"primitive": "GRASP", "start_s": 1, "end_s": 2}
    result = evaluate({"video_id": "v", "actions": [a]}, {"actions": [a, a], "inference_mode": "fixture"})
    assert result["metrics"]["actions"]["precision"] == .5
    assert result["metrics"]["actions"]["recall"] == 1

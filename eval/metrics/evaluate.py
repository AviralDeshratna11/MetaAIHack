"""Evaluate independent annotations; unknown annotations produce not_evaluated."""
import argparse
import json
from pathlib import Path

import numpy as np

from packages.video.masks import decode_rle


def temporal_iou(a, b):
    intersection = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union > 0 else 0.


def evaluate(annotation, prediction):
    report = {"schema_version": "0.1.0", "video_id": annotation["video_id"],
              "inference_mode": prediction.get("inference_mode", "unknown"),
              "model_config": prediction.get("model_config", {}), "metrics": {}}
    metrics = report["metrics"]
    ground, predicted = annotation.get("actions"), prediction.get("actions", [])
    if ground is None:
        metrics["actions"] = {"status": "not_evaluated"}
    else:
        # Greedy maximum temporal overlap, same primitive, one-to-one; tIoU >= .5.
        candidates = sorted([(temporal_iou((a["start_s"], a["end_s"]), (b["start_s"], b["end_s"])), i, j)
            for i, a in enumerate(ground) for j, b in enumerate(predicted) if a["primitive"] == b["primitive"]], reverse=True)
        used_a, used_b, matches = set(), set(), []
        for score, i, j in candidates:
            if score >= .5 and i not in used_a and j not in used_b:
                used_a.add(i); used_b.add(j); matches.append((score, ground[i], predicted[j]))
        tp = len(matches)
        precision = tp / len(predicted) if predicted else None
        recall = tp / len(ground) if ground else None
        f1 = 2 * tp / (len(ground) + len(predicted)) if ground or predicted else None
        errors = [abs(a[k] - b[k]) for _, a, b in matches for k in ("start_s", "end_s")]
        metrics["actions"] = {"status": "evaluated", "precision": precision, "recall": recall, "f1": f1,
            "matched": tp, "annotated_count": len(ground), "predicted_count": len(predicted),
            "mean_temporal_iou_matched": float(np.mean([m[0] for m in matches])) if matches else None,
            "median_boundary_error_s_matched": float(np.median(errors)) if errors else None}
    masks = annotation.get("selected_masks")
    if masks is None:
        metrics["mask_iou"] = {"status": "not_evaluated"}
    else:
        scores = []
        for target in masks:
            truth = decode_rle(target["mask"])
            pred = prediction.get("masks", {}).get(target["key"])
            if pred is None:
                scores.append(0.)
                continue
            candidate = decode_rle(pred)
            if candidate.shape != truth.shape:
                raise ValueError("Mask coordinate/dimension mismatch")
            union = np.logical_or(truth, candidate).sum()
            scores.append(float(np.logical_and(truth, candidate).sum() / union) if union else None)
        valid = [s for s in scores if s is not None]
        metrics["mask_iou"] = {"status": "evaluated", "mean": float(np.mean(valid)) if valid else None,
                               "annotated_frames": len(masks), "nonempty_unions": len(valid)}
    identity = annotation.get("identity_frames")
    if identity is None:
        metrics["identity"] = {"status": "not_evaluated"}
    else:
        visible = sorted([a for a in identity if a["visible"] is True], key=lambda a: (a["entity_id"], a["frame_index"]))
        correct = switches = 0
        previous = {}
        for a in visible:
            key = f"{a['frame_index']}/{a['entity_id']}"
            actual = prediction.get("identity_frames", {}).get(key)
            if actual == a["physical_object_id"]:
                correct += 1
            if actual is not None:
                # Identity switches require independently annotated physical associations.
                entity = a["entity_id"]
                if entity in previous and previous[entity] != actual:
                    switches += 1
                previous[entity] = actual
        metrics["identity"] = {"status": "evaluated", "visible_annotated_frames": len(visible),
            "correct_fraction": correct / len(visible) if visible else None, "id_switches": switches}
    recovery = annotation.get("occlusion_recovery")
    if recovery is None:
        metrics["occlusion_recovery"] = {"status": "not_evaluated"}
    else:
        observed = prediction.get("occlusion_recovery", {})
        values = [observed.get(event["event_id"]) == event["physical_object_id"] for event in recovery]
        metrics["occlusion_recovery"] = {"status": "evaluated", "annotated_events": len(values),
                                        "correct_fraction": sum(values) / len(values) if values else None}
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation", type=Path)
    parser.add_argument("prediction", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.annotation.read_text()), json.loads(args.prediction.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

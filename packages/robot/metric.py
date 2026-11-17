"""Meters per reconstruction unit, estimated from the person in the video.

Monocular reconstruction has no absolute scale. SAM 3D Body does: its skeleton is
in meters. Each accepted body-to-scene alignment stores how many scene units one
body meter spans, so its inverse is a metric scale for that frame. The median over
frames is used and the spread is reported. This assumes an average-sized adult
and inherits the body model's error; it is an estimate, never a measurement.

When no body alignment exists, the hand's own surface points give a coarser
estimate from a typical visible hand length.
"""
import numpy as np

TYPICAL_HAND_M = .17  # visible adult hand, wrist crease to fingertips, partly curled
MIN_ALIGNMENTS = 2


def estimate_scale(alignments=None, hand_rows=None, hand_id=None):
    """Returns {"scale_m_per_unit", "source", "samples", "relative_spread", "note"} or None."""
    fits = [a for a in alignments or [] if str(a.get("alignment_id", "")).startswith("body-") and a.get("scale", 0) > 0]
    # Prefer the manipulating hand's own alignments; any alignment of the same person will do.
    own = [a for a in fits if hand_id is not None and f"-{hand_id}-" in a["alignment_id"]]
    body = [1/a["scale"] for a in (own if len(own) >= MIN_ALIGNMENTS else fits)]
    if len(body) >= MIN_ALIGNMENTS:
        scale = float(np.median(body))
        return {"scale_m_per_unit": scale, "source": "body_scale_estimate", "samples": len(body),
                "relative_spread": float(np.subtract(*np.percentile(body, [75, 25]))/scale),
                "note": "Median inverse scale of SAM 3D Body skeleton alignments; assumes an average-sized adult"}
    return _from_hand(hand_rows, hand_id)


def _from_hand(hand_rows, hand_id):
    lengths = []
    for row in hand_rows or []:
        if (hand_id is not None and row.get("entity_id") != hand_id) or row.get("pose") is None:
            continue
        points = np.asarray(row.get("points_world") or [], float)
        if len(points) < 16:
            continue
        # Longest principal extent of the visible hand surface, robust to stray points.
        centered = points-points.mean(0)
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        along = centered @ vt[0]
        lengths.append(float(np.subtract(*np.percentile(along, [97.5, 2.5]))))
    if len(lengths) < MIN_ALIGNMENTS:
        return None
    length = float(np.median(lengths))
    return {"scale_m_per_unit": TYPICAL_HAND_M/length, "source": "hand_extent_estimate", "samples": len(lengths),
            "relative_spread": float(np.subtract(*np.percentile(lengths, [75, 25]))/length),
            "note": f"Visible hand length taken as {TYPICAL_HAND_M} m; coarse, depends on how much of the hand is visible"}

"""Propose semantic-to-track associations the tracker refused to guess.

The tracker leaves an entity unassigned whenever its concept returns more than one
candidate. The semantic plan and the stored tracks usually contain enough to decide:

- one thing re-detected under a new id: its candidates never coexist, so they are
  stitched into one identity;
- two hands: the plan says what each does and when, and sometimes which side of the
  image it is on; candidates differ in motion during those intervals and in position;
- several similar objects: the one the acting hand stays close to is the one acted on.

Every proposal carries its margin. Nothing is proposed when the evidence does not
separate the candidates. Proposals are heuristics and are recorded as unreviewed.
"""
from collections import defaultdict
from itertools import permutations

import numpy as np

MARGIN = .15  # required gap between the best and the next-best assignment
STILL = ("PRESS", "UNKNOWN")  # primitives that describe holding, not moving
COEXIST = .1  # candidates sharing fewer frames than this share are one thing seen twice
CLOSER = .6  # an object candidate must be this much closer to the acting hand than the next


def observed(rows):
    return [r for r in rows if r["observed"]]


def motion(rows, intervals=None):
    """Path length of a candidate's normalized centroid, optionally inside time intervals."""
    total, previous = 0., None
    for row in sorted(rows, key=lambda r: r["frame_index"]):
        inside = intervals is None or any(a <= row["timestamp"] <= b for a, b in intervals)
        if not row["observed"] or not inside:
            previous = None
            continue
        point = np.array(row["centroid_normalized"])
        if previous is not None:
            total += float(np.linalg.norm(point-previous))
        previous = point
    return total


def exclusive(intervals, others):
    """Parts of an entity's active intervals where no other entity of the group is active."""
    result = []
    for start, end in intervals:
        cuts = sorted({start, end, *(t for a, b in others for t in (a, b) if start < t < end)})
        for a, b in zip(cuts, cuts[1:]):
            middle = (a+b)/2
            if not any(c <= middle <= d for c, d in others):
                result.append((a, b))
    return result


def image_side(name):
    """'left' or 'right' when the plan places the entity on a side of the frame."""
    text = name.lower().replace("-", " ")
    left = any(w in text for w in ("left side", "on the left", "left of"))
    right = any(w in text for w in ("right side", "on the right", "right of"))
    return "left" if left and not right else "right" if right and not left else None


def anchor(rows):
    return max(observed(rows), key=lambda r: (r["bbox_xyxy"][2]-r["bbox_xyxy"][0])*(r["bbox_xyxy"][3]-r["bbox_xyxy"][1]))["frame_index"]


def proposal(entity, shot, ids, rows, evidence, score, margin):
    first = ids[0]
    payload = {"entity_id": entity, "shot_id": shot, "frame_index": anchor(rows[first]), "kind": "association", "provider_track_id": first,
               "reviewed_by": "heuristic", "score": round(float(score), 3), "margin": round(float(margin), 3), "evidence": evidence+" Not human reviewed."}
    if len(ids) > 1:
        payload["provider_track_ids"] = list(ids)
    return payload


def propose(tracks, plan):
    """Returns (proposals, reasons). Each proposal is an association correction payload."""
    entities = {e["entity_id"]: e for e in plan["entities"]}
    groups = defaultdict(lambda: defaultdict(list))
    for row in tracks:
        if row["provider_track_id"] is not None:
            groups[(row["shot_id"], row["entity_id"])][row["provider_track_id"]].append(row)
    settled = {key: next(i for i, rows in c.items() if any(r["identity_status"] == "associated" for r in rows))
               for key, c in groups.items() if any(r["identity_status"] == "associated" for rows in c.values() for r in rows)}
    pending = {key: c for key, c in groups.items() if key not in settled
               and (len(c) > 1 or any(r["identity_status"] == "ambiguous" for rows in c.values() for r in rows))}
    proposals, reasons, chosen = [], [], {key: [i] for key, i in settled.items()}
    # Entities prompted with the same concept see the same candidates and are resolved together.
    clusters = defaultdict(list)
    for shot, entity in pending:
        clusters[(shot, entities[entity]["sam_prompt"].strip().casefold())].append(entity)
    singles = []
    for (shot, _), members in sorted(clusters.items()):
        if len(members) == 1:
            singles.append((shot, members[0]))
            continue
        candidates = pending[(shot, members[0])]
        ids = sorted(candidates)
        if len(members) > len(ids):
            reasons.append(f"{shot}: {len(members)} entities share {len(ids)} candidates; left for review")
            continue
        active = {e: [(a["start_s"], a["end_s"]) for a in plan["actions"] if a.get("actor") == e and a["primitive"] not in STILL] for e in members}
        centers = {i: float(np.mean([r["centroid_normalized"][0] for r in observed(rows)])) for i, rows in candidates.items() if observed(rows)}
        scores, used = {}, set()
        for entity in members:
            cues = {}
            # Motion in the intervals where only this entity is described as acting separates
            # two hands even when both are "manipulating".
            alone = exclusive(active[entity], [x for other in members if other != entity for x in active[other]])
            window = alone or active[entity]
            moved = {i: motion(candidates[i], window or None) for i in ids}
            total = sum(moved.values())
            role = entities[entity]["motion"]
            if total > 1e-9 and (role == "static" or (role == "manipulated" and window)):
                cues["motion"] = {i: (moved[i]/total if role == "manipulated" else 1-moved[i]/total) for i in ids}
            side = image_side(entities[entity]["semantic_name"])
            if side and len(centers) == len(ids) and max(centers.values())-min(centers.values()) > .08:
                edge = min(centers, key=centers.get) if side == "left" else max(centers, key=centers.get)
                cues["image side"] = {i: float(i == edge) for i in ids}
            used |= cues.keys()
            for i in ids:
                scores[(entity, i)] = float(np.mean([cue[i] for cue in cues.values()])) if cues else 1/len(ids)
        ranked = sorted(((sum(scores[(e, i)] for e, i in zip(members, order))/len(members), order)
                         for order in permutations(ids, len(members))), reverse=True)
        best, order = ranked[0]
        margin = best-ranked[1][0] if len(ranked) > 1 else best
        if margin < MARGIN:
            reasons.append(f"{shot}: candidates for {', '.join(members)} are not separated by motion role or image side (margin {margin:.2f}); left for review")
            continue
        for entity, pick in zip(members, order):
            if not observed(candidates[pick]):
                continue
            chosen[(shot, entity)] = [pick]
            proposals.append(proposal(entity, shot, [pick], candidates, f"Automatic association by {' and '.join(sorted(used))}: "
                f"'{entities[entity]['semantic_name']}' matches candidate {pick} with score {scores[(entity, pick)]:.2f} (assignment margin {margin:.2f}).",
                scores[(entity, pick)], margin))
    for shot, entity in sorted(singles):
        candidates = {i: rows for i, rows in pending[(shot, entity)].items() if observed(rows)}
        ids = sorted(candidates, key=lambda i: min(r["frame_index"] for r in observed(candidates[i])))
        if not ids:
            continue
        frames = {i: {r["frame_index"] for r in observed(candidates[i])} for i in ids}
        shared = max((len(frames[a] & frames[b])/min(len(frames[a]), len(frames[b])) for a in ids for b in ids if a < b), default=0.)
        if len(ids) == 1 or shared < COEXIST:
            # Never visible together: one thing that the tracker lost and found again.
            chosen[(shot, entity)] = ids
            proposals.append(proposal(entity, shot, ids, candidates, f"Automatic stitching: the {len(ids)} candidate(s) for "
                f"'{entities[entity]['semantic_name']}' share {shared:.0%} of their frames, so they are one thing seen in turn.", 1-shared, 1-shared))
            continue
        # Several coexisting look-alikes: the one the acting hand stays near is the one acted on.
        actions = [a for a in plan["actions"] if a.get("object") == entity and (shot, a.get("actor")) in chosen]
        distances = {}
        for i in ids:
            values = []
            for action in actions:
                hand_rows = [r for pick in chosen[(shot, action["actor"])] for r in observed(groups[(shot, action["actor"])][pick])
                             if action["start_s"] <= r["timestamp"] <= action["end_s"]]
                hand = {r["frame_index"]: np.array(r["centroid_normalized"]) for r in hand_rows}
                values += [float(np.linalg.norm(np.array(r["centroid_normalized"])-hand[r["frame_index"]]))
                           for r in observed(candidates[i]) if r["frame_index"] in hand]
            if len(values) >= 5:
                distances[i] = float(np.mean(values))
        ordered = sorted(distances, key=distances.get)
        if len(ordered) >= 2 and distances[ordered[0]] < CLOSER*distances[ordered[1]]:
            near = ordered[0]
            chosen[(shot, entity)] = [near]
            ratio = distances[near]/distances[ordered[1]]
            proposals.append(proposal(entity, shot, [near], candidates, f"Automatic association by hand proximity: candidate {near} of "
                f"'{entities[entity]['semantic_name']}' is {ratio:.0%} as far from the acting hand as the next candidate.", 1-ratio, 1-ratio))
            continue
        # A lone manipulating entity among coexisting look-alikes (a hand and bystanders'
        # hands): the candidate that carries the motion during its own actions.
        active = [(a["start_s"], a["end_s"]) for a in plan["actions"] if a.get("actor") == entity and a["primitive"] not in STILL]
        moved = {i: motion(candidates[i], active) for i in ids} if active and entities[entity]["motion"] == "manipulated" else {}
        total = sum(moved.values())
        shares = sorted(((moved[i]/total, i) for i in ids), reverse=True) if total > 1e-9 else []
        if shares and shares[0][0]-shares[1][0] >= MARGIN:
            share, pick = shares[0]
            chosen[(shot, entity)] = [pick]
            proposals.append(proposal(entity, shot, [pick], candidates, f"Automatic association by motion: candidate {pick} carries {share:.0%} of the "
                f"motion during the actions of '{entities[entity]['semantic_name']}'.", share, share-shares[1][0]))
        else:
            reasons.append(f"{shot}: candidates for {entity} coexist and are not separated by hand proximity or motion; left for review")
    return proposals, reasons

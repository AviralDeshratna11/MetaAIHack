"""Independent contact evidence fusion; semantic requirements never prove contact."""
import json
from collections import defaultdict, deque

import cv2
import numpy as np

from packages.geometry.math3d import pose_matrix, transform_points
from packages.geometry.tables import write_contracts
from packages.schemas.reconstruction import (AffordancePatch, ContactFrame, InteractionEvent,
    RefinedAction)
from workers.geometry.reconstruct import selected_tracks


def mask_distance(hand, obj):
    if not hand.any() or not obj.any(): return None
    distance = cv2.distanceTransform((obj == 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return float(distance[hand > 0].min())


def point_distance(hand, obj):
    h, o = np.asarray(hand, float), np.asarray(obj, float)
    if len(h) == 0 or len(o) == 0: return None, None
    distances = np.linalg.norm(h[:, None] - o[None, :], axis=2)
    i, j = np.unravel_index(np.argmin(distances), distances.shape)
    return float(distances[i, j]), o[j]


def motion_score(history):
    if len(history) < 3: return None
    h = np.diff(np.array([x[0] for x in history]), axis=0)
    o = np.diff(np.array([x[1] for x in history]), axis=0)
    hn, on = np.linalg.norm(h), np.linalg.norm(o)
    if min(hn, on) < .5: return None  # Stationarity is not evidence of a grasp.
    cosine = min(1., max(0., float(np.sum(h*o) / (hn*on))))
    return float(cosine * np.exp(-np.linalg.norm(h-o) / (hn+on)))


def refine_actions(plan, events, window):
    result = []
    for action in plan.actions:
        row = RefinedAction(action_id=action.action_id, primitive=action.primitive,
            semantic_start_s=action.start_s, semantic_end_s=action.end_s)
        kinds = {"GRASP": "grasp_candidate", "RELEASE": "release_candidate", "PLACE": "release_candidate"}
        kind = kinds.get(action.primitive.value)
        if kind:
            matches = [e for e in events if e["kind"] == kind and e["object_id"] == action.object
                and (action.actor is None or e["hand_id"] == action.actor)
                and abs(e["timestamp"]-action.start_s) <= window]
            if matches:
                event = min(matches, key=lambda e: abs(e["timestamp"]-action.start_s))
                # Keep the semantic end; never silently reverse/collapse an interval.
                if event["timestamp"] < action.end_s:
                    row.refined_start_s = event["timestamp"]
                    row.refined_end_s = action.end_s
                    row.timing_source = "contact_candidate"
                    row.evidence_event_ids = [event["event_id"]]
                    row.review_reasons.append("Candidate boundary from uncalibrated contact fusion; support state unverified")
            if row.refined_start_s is None:
                row.review_reasons.append("No supported contact transition within the semantic search window")
        else:
            row.review_reasons.append("Retained semantic timing; no validated physical boundary detector for this primitive")
        result.append(row.model_dump(mode="json"))
    return result


def fuse_interactions(manifest, plan, tracks, masks, hands, objects, output, config, mode):
    output.mkdir(parents=True, exist_ok=True)
    measured = selected_tracks(tracks)
    poses = {(r["frame_index"], r["entity_id"]): r for r in hands+objects}
    actors = [e for e in plan.entities if e.role == "actor"]
    targets = [e for e in plan.entities if e.role != "actor"]
    rows, events, patches = [], [], []
    for shot in manifest.shots:
        for hand in actors:
            for obj in targets:
                history, identity, active = deque(maxlen=5), None, False
                on_count = off_count = 0
                on_samples = set()
                geometry = None
                for frame in range(shot.start_frame, shot.end_frame):
                    t = frame * manifest.fps_den / manifest.fps_num
                    ht, ot = measured.get((frame, hand.entity_id)), measured.get((frame, obj.entity_id))
                    row = ContactFrame(shot_id=shot.shot_id, frame_index=frame, timestamp=t,
                        hand_id=hand.entity_id, object_id=obj.entity_id, state="UNKNOWN", evidence_origin="missing")
                    current = (ht["track_id"], ot["track_id"]) if ht and ot else None
                    if current != identity or current is None:
                        history.clear()
                        on_samples.clear()
                        active, on_count, off_count, geometry = False, 0, 0, None
                    identity = current
                    if current is None:
                        row.warnings.append("Missing or ambiguous measured identity; contact unassessed")
                        rows.append(row.model_dump(mode="json"))
                        continue
                    row.hand_track_id, row.object_track_id = current
                    hm, om = masks(ht["mask_ref"]), masks(ot["mask_ref"])
                    d2 = mask_distance(hm, om)
                    row.distance_2d_px = d2
                    history.append((ht["centroid"], ot["centroid"]))
                    row.motion_coupling = motion_score(history)
                    hp, op = poses.get((frame, hand.entity_id)), poses.get((frame, obj.entity_id))
                    if hp and op and hp["pose"] and op["pose"] and hp["track_id"] == current[0] and op["track_id"] == current[1]:
                        d3, patch = point_distance(hp["points_world"], op["points_world"])
                        geometry = (t, d3, patch, op)
                    if geometry and t-geometry[0] <= .25 + 1e-8:
                        row.geometry_age_s = t-geometry[0]
                        row.geometry_origin = "sampled" if row.geometry_age_s < 1e-8 else "held"
                        row.distance_3d_relative = geometry[1]
                    else:
                        geometry = None
                    action = next((a for a in plan.actions if a.actor == hand.entity_id and a.object == obj.entity_id
                        and a.start_s <= t < a.end_s and a.requires_contact is not None), None)
                    row.semantic_prior = float(action.requires_contact) if action else None
                    s2 = np.exp(-d2/config["contact_distance_2d_px"]) if d2 is not None else 0.
                    s3 = np.exp(-row.distance_3d_relative/config["contact_distance_3d_relative"]) if row.distance_3d_relative is not None else 0.
                    score = float(.35*s2 + .35*s3 + .2*(row.motion_coupling or 0) + .1*(row.semantic_prior or 0))
                    row.probability = score if d2 is not None else None
                    row.evidence_origin = "synthetic" if mode == "fixture" else "estimated"
                    enough = d2 is not None and row.distance_3d_relative is not None
                    on_count = on_count+1 if enough and score >= config["contact_on"] else 0
                    if on_count == 0:
                        on_samples.clear()
                    elif geometry is not None:
                        on_samples.add(geometry[0])
                    negative_evidence = enough or (d2 is not None and d2 > 2*config["contact_distance_2d_px"])
                    off_count = off_count+1 if negative_evidence and score <= config["contact_off"] else 0
                    transition = None
                    # Reusing one 3D sample across adjacent frames must not turn a
                    # single-frame spike into independent persistence evidence.
                    if on_count >= config["persistence_frames"] and len(on_samples) >= 2 and not active:
                        active, transition = True, "contact_on"
                    elif off_count >= config["persistence_frames"] and active:
                        active, transition = False, "contact_off"
                    if enough and active:
                        row.state = "CONTACT"
                    elif d2 is not None and d2 > 2*config["contact_distance_2d_px"]:
                        row.state = "NO_CONTACT"
                    elif d2 is not None:
                        row.state = "CANDIDATE"
                    if geometry and row.state == "CONTACT" and row.geometry_origin == "sampled":
                        transform = pose_matrix(geometry[3]["pose"])
                        if transform is not None and geometry[2] is not None:
                            patch = transform_points([geometry[2]], np.linalg.inv(transform))[0].tolist()
                            row.contact_points_object = [patch]
                            patches.append(AffordancePatch(object_id=obj.entity_id, hand_id=hand.entity_id,
                                shot_id=shot.shot_id, frame_index=frame, contact_patch_object_xyz=[patch],
                                source="synthetic" if mode == "fixture" else "estimated_surface_proximity").model_dump(mode="json"))
                    if transition:
                        event = InteractionEvent(event_id=f"{shot.shot_id}:{hand.entity_id}:{obj.entity_id}:{frame}:{transition}",
                            shot_id=shot.shot_id, frame_index=frame, timestamp=t, hand_id=hand.entity_id,
                            object_id=obj.entity_id, kind=transition, confidence=score,
                            reasons=["Persistent multi-channel heuristic transition; not measured force/contact"])
                        events.append(event.model_dump(mode="json"))
                        if row.motion_coupling is not None and row.motion_coupling > .6 and transition == "contact_on":
                            candidate = event.model_copy(update={"event_id": event.event_id+":grasp", "kind": "grasp_candidate",
                                "reasons": ["Rising contact and coupled motion; unsupported motion has not been independently established"]})
                            events.append(candidate.model_dump(mode="json"))
                        elif transition == "contact_off":
                            candidate = event.model_copy(update={"event_id": event.event_id+":release", "kind": "release_candidate",
                                "reasons": ["Falling contact; object support and hand withdrawal require review"]})
                            events.append(candidate.model_dump(mode="json"))
                    if row.distance_3d_relative is None:
                        row.warnings.append("No recent aligned 3D evidence; 2D proximity alone cannot establish contact")
                    if row.geometry_origin == "held":
                        row.warnings.append("3D evidence held from a recent sample; not a measured current-frame distance")
                    rows.append(row.model_dump(mode="json"))
    rows = write_contracts(output / "contacts.parquet", ContactFrame, rows)
    refined = refine_actions(plan, events, config["boundary_window_s"])
    (output / "interaction_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (output / "refined_actions.json").write_text(json.dumps(refined, indent=2), encoding="utf-8")
    (output / "affordance_patches.json").write_text(json.dumps(patches, indent=2), encoding="utf-8")
    report = {"schema_version": "0.2.0", "contact_frames": sum(r["state"] == "CONTACT" for r in rows),
        "contact_events": len(events), "unknown_frames": sum(r["state"] == "UNKNOWN" for r in rows),
        "calibration": "uncalibrated weighted score; probability is not an empirical probability",
        "weights": {"mask_proximity": .35, "geometry_proximity": .35, "motion_coupling": .2, "semantic_prior": .1},
        "geometry_hold_seconds": .25, "thresholds": config,
        "review_reasons": ["Support state, force/contact and grasp validity remain unverified; events are candidates",
                           "Contact thresholds require calibration on manually annotated real clips"]}
    (output / "interaction_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

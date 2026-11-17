"""Synthetic human demonstrations of articulated tasks, as real ITR contracts.

Used for diagnostics and tests only. The hand path is generated in an arbitrary
relative-scale, camera-like world (y down) with noise, so nothing downstream can
rely on absolute coordinates. These are never evidence of live model accuracy.
"""
import numpy as np

from packages.robot.articulated import axis_rotation
from packages.schemas.models import ActionGraph, Entity
from packages.schemas.reconstruction import (ContactFrame, InteractionFrame, InteractionPose, InteractionTrajectory,
    Pose3D, RefinedAction, ReconstructionReport)

DEMOS = {
    "laptop_lid": {"kind": "revolute", "amount": 1.75, "primitive": "OPEN", "object": "laptop", "task": "Open the laptop lid"},
    "close_lid": {"kind": "revolute", "amount": -1.4, "primitive": "CLOSE", "object": "laptop", "task": "Close the laptop lid"},
    "drawer": {"kind": "prismatic", "amount": 1., "primitive": "PULL", "object": "drawer", "task": "Open the drawer"},
    "close_drawer": {"kind": "prismatic", "amount": -1., "primitive": "PUSH", "object": "drawer", "task": "Push the drawer shut"},
    "door": {"kind": "door", "amount": 1.1, "primitive": "OPEN", "object": "cabinet door", "task": "Open the cabinet door"},
    # Free object: carried across and set down on a higher surface, or picked up and kept in the hand.
    "pick_place": {"kind": "carry", "amount": .2, "rise": .06, "primitive": "TRANSPORT", "object": "mug", "task": "Move the mug onto the stand"},
    "pick_up": {"kind": "carry", "amount": .05, "rise": .12, "held": True, "primitive": "LIFT", "object": "cup", "task": "Pick up the cup"},
    # The hand stays in place: only the semantic plan says what was done.
    "press_button": {"kind": "still", "amount": 0, "primitive": "PRESS", "object": "button", "task": "Press the button"},
    "turn_knob": {"kind": "still", "amount": 0, "primitive": "ROTATE", "object": "knob", "task": "Turn the knob"},
}


def demonstration(name="laptop_lid", seed=0, noise=.004, fps=8., scale=2.7, video_id="synthetic-demo"):
    """Returns (ITR, truth). Lengths are multiplied by an arbitrary scale; noise is relative to it."""
    spec, random = DEMOS[name], np.random.default_rng(seed)
    up = np.array([0, -1., 0])  # OpenCV-style world: +y is down
    heading = random.uniform(0, 2*np.pi)
    forward = axis_rotation(up, heading) @ np.array([0, 0, 1.])  # horizontal, away from the camera
    side = np.cross(up, forward)
    center = np.array([.1, .2, 1.4])+random.normal(0, .05, 3)
    amount = spec["amount"]
    if spec["kind"] == "revolute":
        radius = .24
        # Hinge along `side`; closed lid extends toward the camera (-forward) and lifts up.
        start_angle = 0 if amount > 0 else -amount
        handle = lambda a: center+radius*(-np.cos(a)*forward+np.sin(a)*up)
        path = lambda s: handle(start_angle+s*amount)
        reach_from = path(0)-.25*forward+.12*up
    elif spec["kind"] == "carry":
        radius, travel = None, spec["amount"]
        path = lambda s: center+s*travel*side+(spec["rise"]*s+.08*np.sin(np.pi*s))*up
        reach_from = center-.25*forward+.15*up
    elif spec["kind"] == "still":
        radius, travel = None, 0.
        path = lambda s: center-.004*s*up
        reach_from = center-.15*forward+.2*up
    elif spec["kind"] == "door":
        radius = .3
        handle = lambda a: center+radius*(np.cos(a)*side-np.sin(a)*forward)
        path = lambda s: handle(s*amount)
        reach_from = path(0)-.3*forward
    else:
        radius, travel = None, .22
        # Opening pulls toward the camera; the reach goes the other way.
        origin = center if amount > 0 else center-travel*forward
        path = lambda s: origin-np.sign(amount)*s*travel*forward
        reach_from = origin-.3*forward+.05*up if amount > 0 else origin-.3*forward
    durations = {"approach": .9, "manipulate": 1.6, "retreat": .6}
    times = np.arange(0, sum(durations.values())+1e-9, 1/fps)
    smooth = lambda u: 3*u**2-2*u**3
    frames = []
    for index, t in enumerate(times):
        if t < durations["approach"]:
            hand, contact, progress = reach_from+smooth(t/durations["approach"])*(path(0)-reach_from), False, 0.
        elif t <= durations["approach"]+durations["manipulate"]:
            progress = smooth((t-durations["approach"])/durations["manipulate"])
            hand, contact = path(progress), True
        elif spec.get("held"):
            hand, contact, progress = path(1), True, 1.
        else:
            u = smooth((t-durations["approach"]-durations["manipulate"])/durations["retreat"])
            hand, contact, progress = path(1)+u*.15*(reach_from-path(0))/np.linalg.norm(reach_from-path(0)), False, 1.
        # The tracked object centroid follows the moving part only partially.
        thing = center+.5*(path(progress)-center) if radius else path(progress)-.1*forward
        hand = (hand+random.normal(0, noise, 3))*scale
        thing = (thing+random.normal(0, noise, 3))*scale
        frame_index = int(round(t*30))
        pose = lambda p, entity, track: InteractionPose(entity_id=entity, track_id=track, origin="synthetic",
            representation="surface_centroid", pose=Pose3D(position_xyz=p.tolist()))
        frames.append(InteractionFrame(shot_id="shot_000", world_frame="synthetic_camera_world", frame_index=frame_index,
            timestamp=float(t), hands=[pose(hand, "HAND", "hand:0")], objects=[pose(thing, "OBJECT", "object:0")],
            contacts=[ContactFrame(shot_id="shot_000", frame_index=frame_index, timestamp=float(t), hand_id="HAND", object_id="OBJECT",
                hand_track_id="hand:0", object_track_id="object:0", state="CONTACT" if contact else "NO_CONTACT",
                geometry_origin="sampled", motion_coupling=.9 if contact else .1, evidence_origin="synthetic")],
            current_action_ids=["a1"]))
    report = ReconstructionReport(source_run_id="synthetic-perception", backend="synthetic", inference_mode="fixture",
        world_frames=["synthetic_camera_world"], sampled_frames=[f.frame_index for f in frames], camera_frames=len(frames),
        hand_pose_frames=len(frames), object_pose_frames=len(frames), relative_pose_frames=len(frames), contact_frames=len(frames),
        review_reasons=["Synthetic demonstration; not a reconstruction of real footage"])
    entity = lambda i, name, role: Entity(entity_id=i, category=name, semantic_name=name, sam_prompt=name, role=role,
        motion="manipulated" if role != "actor" else "unknown")
    itr = InteractionTrajectory(video_id=video_id, run_id="synthetic-reconstruction", source_run_id="synthetic-perception",
        task=spec["task"], canonical_skill=spec["primitive"].lower(), entities=[entity("HAND", "hand", "actor"), entity("OBJECT", spec["object"], "manipulated_object")],
        action_graph=ActionGraph(nodes=["a1"], edges=[]),
        refined_actions=[RefinedAction(action_id="a1", primitive=spec["primitive"], semantic_start_s=0, semantic_end_s=float(times[-1]))],
        frames=frames, quality=report)
    if spec["kind"] == "carry":
        truth = {"kind": "transport", "template": "object", "direction": "unknown", "amount": float(np.hypot(travel, spec["rise"]))*scale,
                 "released": not spec.get("held", False)}
    elif spec["kind"] == "still":
        truth = {"kind": "static", "template": "button" if spec["primitive"] == "PRESS" else "knob", "direction": "open", "amount": 0.}
    else:
        truth = {"kind": "revolute" if spec["kind"] == "door" else spec["kind"], "amount": abs(amount) if radius else travel*scale,
                 "direction": "open" if amount > 0 else "close", "template": "door" if spec["kind"] == "door" else "lid" if radius else "drawer"}
    truth.update(duration_s=float(times[-1]), scale=scale)
    return itr, truth

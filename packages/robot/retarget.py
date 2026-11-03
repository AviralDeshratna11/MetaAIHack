"""Explicit workspace adaptation, contact-conditioned gripper and retimed IK."""
import numpy as np

from packages.common.utils import DomainError
from packages.geometry.math3d import quaternion_matrix
from packages.schemas.robotization import RobotFrame, RobotTrajectory


def gripper_transition(state, contacts):
    # Loss of observation is unknown, never a release.
    if len(contacts) != 1:
        return "unknown"
    row = contacts[0]
    if row.state == "UNKNOWN" or row.evidence_origin == "missing":
        return "unknown"
    if row.state == "CONTACT" and row.geometry_origin in ("sampled", "held") and (row.motion_coupling or 0) >= .5:
        return "hold" if state in ("closed", "hold") else "closed"
    if row.state == "NO_CONTACT" and row.geometry_origin == "sampled":
        return "open"
    return state if state in ("closed", "hold") else "unknown"


def retarget(itr, config, robot, run_id, continuity=True):
    selected = [f for f in itr.frames if f.shot_id == config.shot_id and config.start_s <= f.timestamp <= config.end_s]
    if not selected:
        raise DomainError("E_ROBOT_INTERVAL", "No frames in selected shot/interval")
    observations = []
    for frame in selected:
        hands = [p for p in frame.hands if p.entity_id == config.hand_id and p.pose is not None]
        objects = [p for p in frame.objects if p.entity_id == config.object_id and p.pose is not None]
        if len(hands) == len(objects) == 1:
            observations.append((frame, hands[0], objects[0]))
    if len(observations) < 2:
        raise DomainError("E_ROBOT_GEOMETRY", "Need at least two associated hand/object pose samples")
    worlds = {f.world_frame for f, _, _ in observations}
    if len(worlds) != 1:
        raise DomainError("E_ROBOT_FRAME", "Cannot retarget across different world frames")
    points, object_anchor, object_driven = [], None, 0
    for frame, hand, obj in observations:
        hp, op = np.array(hand.pose.position_xyz), np.array(obj.pose.position_xyz)
        contacts = [c for c in frame.contacts if c.hand_id == config.hand_id and c.object_id == config.object_id]
        coupled = len(contacts) == 1 and contacts[0].state == "CONTACT" and (contacts[0].motion_coupling or 0) >= .5
        if coupled:
            if object_anchor is None:
                object_anchor = hp-op
            # Preserve object-relative translation through a coupled manipulation.
            # Unknown rigid orientation is never synthesized from PCA.
            points.append(op+object_anchor)
            object_driven += 1
        else:
            object_anchor = None
            points.append(hp)
    points = np.array(points)
    calibration = config.calibration
    transform = np.array(calibration.base_from_world)
    if calibration.mode == "workspace_adaptation":
        center = np.median(points, axis=0)
        extent = float(np.max(np.linalg.norm(points-center, axis=1)))
        scale = config.workspace_extent_m / max(extent, 1e-6)
        targets = (points-center) @ transform[:3, :3].T * scale + config.workspace_center_m
        adaptation = {"mode": calibration.mode, "input_center": center.tolist(), "scale_m_per_unit": scale,
                      "metric_reconstruction": False, "origin": "configured robot workspace", "evidence": calibration.evidence}
    else:
        targets = points @ transform[:3, :3].T * calibration.scale_m_per_unit + transform[:3, 3]
        adaptation = {"mode": calibration.mode, "metric_reconstruction": True, **calibration.model_dump(mode="json")}
    targets += config.tcp_offset_m
    adaptation.update(target_source="Object translation plus contact-onset hand offset during coupled contact; otherwise hand position",
                      object_driven_samples=object_driven, tcp_offset_frame="robot_base")
    rotation = quaternion_matrix(config.tcp_quaternion_xyzw)
    knots, previous, issues = [], robot.home.copy(), list(itr.quality.review_reasons)
    issues += ["Configured task orientation; human wrist orientation is not measured", "Gripper state is inferred; grasp validity is unverified"]
    if calibration.mode == "workspace_adaptation":
        issues.append("Robot workspace adaptation; original physical scale is unknown")
    if observations[0][0].timestamp > selected[0].timestamp or observations[-1][0].timestamp < selected[-1].timestamp:
        issues.append("Selected interval has missing geometry at its boundaries")
    for (frame, hand, obj), target in zip(observations, targets):
        q, pe, re, collisions = robot.ik(target, rotation, previous, continuity)
        reasons = []
        if pe > config.position_tolerance_m: reasons.append("IK_POSITION")
        if re > config.orientation_tolerance_rad: reasons.append("IK_ORIENTATION")
        if collisions: reasons.append("SELF_COLLISION")
        if knots:
            prev = knots[-1]
            if frame.timestamp-prev["frame"].timestamp > config.max_gap_s:
                raise DomainError("E_ROBOT_GEOMETRY_GAP", "Selected interval crosses an unsupported geometry gap; select a continuous interval", 409)
            if hand.track_id != prev["hand_track"] or obj.track_id != prev["object_track"]:
                raise DomainError("E_ROBOT_IDENTITY", "Selected interval crosses a track identity change; select a continuous interval", 409)
        knots.append({"q": q, "frame": frame, "hand_track": hand.track_id, "object_track": obj.track_id,
                      "target": target, "reasons": reasons})
        previous = q
    # Quintic stop-to-stop segments. Analytic maxima bound derivatives before sampling.
    segments, clock = [], 0.
    for i in range(len(knots)-1):
        a, b = knots[i:i+2]
        dq = np.abs(b["q"]-a["q"])
        dt = max(b["frame"].timestamp-a["frame"].timestamp,
                 float(np.max(1.875*dq/robot.velocity)), float(np.max(np.sqrt(5.774*dq/robot.acceleration))), 1/config.control_hz)
        # Round up to a control tick so exported timestamps are a fixed-rate grid.
        dt = np.ceil(dt*config.control_hz)/config.control_hz
        segments.append((clock, dt, a, b))
        clock += dt
    if clock*config.control_hz > 100000:
        raise DomainError("E_ROBOT_DURATION", "Retimed trajectory exceeds frame quota")
    output, state, commanded_width = [], config.initial_gripper, None
    if state != "unknown":
        commanded_width = config.open_width_m if state == "open" else config.closed_width_m
    for index in range(round(clock*config.control_hz)+1):
        t = index/config.control_hz
        segment = next((s for s in segments if t < s[0]+s[1]-1e-9), segments[-1])
        start, dt, a, b = segment
        u = float(np.clip((t-start)/dt, 0, 1))
        s, sd, sdd = 10*u**3-15*u**4+6*u**5, (30*u**2-60*u**3+30*u**4)/dt, (60*u-180*u**2+120*u**3)/dt**2
        q = a["q"]+s*(b["q"]-a["q"])
        velocity, acceleration = sd*(b["q"]-a["q"]), sdd*(b["q"]-a["q"])
        source_t = a["frame"].timestamp+u*(b["frame"].timestamp-a["frame"].timestamp)
        # Left-continuous evidence; never use a future contact to close early.
        source_frame = max((f for f in selected if f.timestamp <= source_t+1e-8), key=lambda f: f.timestamp)
        contact = [c for c in source_frame.contacts if c.hand_id == config.hand_id and c.object_id == config.object_id]
        state = gripper_transition(state, contact)
        desired = config.open_width_m if state == "open" else config.closed_width_m if state in ("closed", "hold") else None
        if desired is None:
            commanded_width = None
        elif commanded_width is None:
            # Initial command is a declared state assumption, not a measured transition.
            commanded_width = desired
        else:
            commanded_width += float(np.clip(desired-commanded_width, -config.max_gripper_speed_m_s/config.control_hz, config.max_gripper_speed_m_s/config.control_hz))
        robot.set_gripper(commanded_width)
        p, r = robot.fk(q)
        from scipy.spatial.transform import Rotation
        target = a["target"]+s*(b["target"]-a["target"])
        pe, re = float(np.linalg.norm(p-target)), float(Rotation.from_matrix(rotation @ r.T).magnitude())
        collisions = robot.collisions()
        reasons = sorted(set(a["reasons"]+b["reasons"]))
        if pe > config.position_tolerance_m: reasons.append("INTERPOLATED_TCP_ERROR")
        if re > config.orientation_tolerance_rad: reasons.append("INTERPOLATED_ORIENTATION_ERROR")
        if collisions: reasons.append("SELF_COLLISION")
        if np.any(np.abs(velocity) > robot.velocity+1e-6): reasons.append("VELOCITY_LIMIT")
        if np.any(np.abs(acceleration) > robot.acceleration+1e-6): reasons.append("ACCELERATION_LIMIT")
        if desired is None: reasons.append("GRIPPER_UNKNOWN")
        output.append(RobotFrame(frame_index=source_frame.frame_index, source_time_s=source_t, execution_time_s=t,
            target_position_m=target.tolist(), achieved_position_m=p.tolist(), target_quaternion_xyzw=config.tcp_quaternion_xyzw,
            joints_rad=q.tolist(), velocity_rad_s=velocity.tolist(), acceleration_rad_s2=acceleration.tolist(),
            gripper_width_m=commanded_width, gripper_state=state, position_error_m=pe, orientation_error_rad=re,
            collisions=collisions, valid=not reasons, reasons=sorted(set(reasons)),
            origin="retargeted" if min(u, 1-u) < 1e-8 else "interpolated"))
    return RobotTrajectory(video_id=itr.video_id, run_id=run_id, source_run_id=itr.run_id, task=itr.task,
        inference_mode=itr.quality.inference_mode, robot=robot.spec, config=config, adaptation=adaptation,
        review_reasons=sorted(set(issues)), frames=output)

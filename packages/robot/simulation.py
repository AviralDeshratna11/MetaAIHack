"""Actual MuJoCo dynamics replay with explicit proxy scene and no object attachment."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np


def replay(trajectory, root, output, render=True):
    import mujoco as mj
    from packages.robot.panda import Panda
    root, output = Path(root), Path(output)
    robot = Panda(root)
    from packages.robot.scenes import scene_xml, forbidden_contacts
    from packages.robot.tasks import TaskEvaluator
    scene = trajectory.config.task_scene
    evaluator = TaskEvaluator(scene) if scene else None
    model = mj.MjModel.from_xml_string(scene_xml(root, scene))
    data = mj.MjData(model)
    qadr = model.jnt_qposadr[robot.joints]
    dadr = model.jnt_dofadr[robot.joints]
    data.qpos[qadr] = trajectory.frames[0].joints_rad
    # Official Panda position actuators control 7 joints, tendon actuator controls fingers 0..255.
    data.ctrl[:7] = trajectory.frames[0].joints_rad
    data.ctrl[7] = (trajectory.frames[0].gripper_width_m or 0)/.08*255
    width = trajectory.frames[0].gripper_width_m
    if width is not None:
        data.qpos[7:9] = width/2
    mj.mj_forward(model, data)
    # Explicit initial equilibration under the same controller, never hidden task execution.
    for _ in range(round(1/model.opt.timestep)):
        mj.mj_step(model, data)
    data.time = 0
    renderer = writer = None
    render_error = None
    if render:
        try:
            renderer = mj.Renderer(model, height=360, width=640)
            writer = cv2.VideoWriter(str(output / "simulation_replay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), trajectory.config.control_hz, (640, 360))
            if not writer.isOpened():
                raise RuntimeError("Video encoder unavailable")
        except Exception as exc:
            render_error = str(exc)
            if renderer: renderer.close()
            if writer: writer.release()
            renderer = writer = None
    rows, violations = [], set()
    peak_velocity, peak_acceleration = np.zeros(7), np.zeros(7)
    hand = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "hand")
    object_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "proxy_object")
    start_object = data.xpos[object_id].copy()
    try:
        for index, frame in enumerate(trajectory.frames):
            # Advance previous control to this timestamp, then record the observation
            # before applying this row's action (standard state/action alignment).
            while data.time < frame.execution_time_s-1e-9:
                previous = trajectory.frames[max(0, index-1)]
                # The action at the preceding observation is this frame's endpoint
                # target. Exporters preserve that causal one-tick alignment.
                alpha = np.clip((data.time-previous.execution_time_s)/max(frame.execution_time_s-previous.execution_time_s,1e-8),0,1)
                data.ctrl[:7] = np.array(previous.joints_rad)*(1-alpha)+np.array(frame.joints_rad)*alpha
                if previous.gripper_width_m is not None and frame.gripper_width_m is not None:
                    data.ctrl[7] = ((1-alpha)*previous.gripper_width_m+alpha*frame.gripper_width_m)/.08*255
                mj.mj_step(model, data)
                peak_velocity = np.maximum(peak_velocity, np.abs(data.qvel[dadr]))
                peak_acceleration = np.maximum(peak_acceleration, np.abs(data.qacc[dadr]))
                if np.any(np.abs(data.qvel[dadr]) > robot.velocity+.01): violations.add("JOINT_VELOCITY")
                if np.any(np.abs(data.qacc[dadr]) > robot.acceleration+.1): violations.add("JOINT_ACCELERATION")
                if np.any(data.qpos[qadr] < robot.lower-.005) or np.any(data.qpos[qadr] > robot.upper+.005): violations.add("JOINT_POSITION")
            data.ctrl[:7] = frame.joints_rad
            if frame.gripper_width_m is not None:
                data.ctrl[7] = frame.gripper_width_m/.08*255
            p = data.xpos[hand]+data.xmat[hand].reshape(3, 3) @ robot.local_tcp
            error = float(np.linalg.norm(p-frame.target_position_m))
            contacts = forbidden_contacts(model, data, allowed_grasp=bool(scene and scene.task == "pick_place"))
            if contacts: violations.add("COLLISION")
            if error > trajectory.config.simulation_tracking_tolerance_m: violations.add("TCP_TRACKING")
            if np.any(data.qpos[qadr] < robot.lower-.005) or np.any(data.qpos[qadr] > robot.upper+.005): violations.add("JOINT_POSITION")
            if np.any(np.abs(data.qvel[dadr]) > robot.velocity+.01): violations.add("JOINT_VELOCITY")
            if np.any(np.abs(data.qacc[dadr]) > robot.acceleration+.1): violations.add("JOINT_ACCELERATION")
            if not np.isfinite(data.qpos).all(): raise RuntimeError("Nonfinite simulated state")
            task = evaluator.evaluate(p, data.xpos[object_id], float(data.qpos[7]+data.qpos[8]),
                0 if index == 0 else frame.execution_time_s-trajectory.frames[index-1].execution_time_s,
                violations) if evaluator else None
            rows.append({"execution_time_s": frame.execution_time_s, "source_time_s": frame.source_time_s,
                "sim_time_s": float(data.time),
                "joints_rad": data.qpos[qadr].tolist(), "joint_velocity_rad_s": data.qvel[dadr].tolist(),
                "tcp_position_m": p.tolist(), "gripper_width_m": float(data.qpos[7]+data.qpos[8]),
                "tracking_error_m": error, "contacts": contacts, "proxy_object_position_m": data.xpos[object_id].tolist(), "task": task})
            if renderer:
                renderer.update_scene(data, camera="debug")
                writer.write(cv2.cvtColor(renderer.render(), cv2.COLOR_RGB2BGR))
    finally:
        if renderer: renderer.close()
        if writer: writer.release()
    report = {"engine": "mujoco", "version": mj.__version__, "seed": 0, "timestep_s": model.opt.timestep,
        "controller": "official Panda position actuators; action specifies next-tick endpoint; linear interpolation from current command; zero velocity feedforward", "initial_equilibration_s": 1, "physics_stepped": True,
        "scene": "assumed plane and free 0.1kg box proxy; not reconstructed task scene", "grasp_attachment": False,
        "unknown_gripper_behavior": "No inferred command; holds prior simulator control, with closed proxy initialization when initial state is unknown. Never an accepted training action.",
        "task_success": bool(evaluator.success) if evaluator else None, "fluid_transfer_success": None,
        "task_scene_validated": False,
        "configured_simulation_task": scene.model_dump(mode="json") if scene else None,
        "simulation_task_success": bool(evaluator.success) if evaluator else None,
        "source_task_validated": False, "grasp_contact_allowance": "finger-object only" if scene and scene.task == "pick_place" else None,
        "violations": sorted(violations), "passed": not violations,
        "tracking_max_m": max(r["tracking_error_m"] for r in rows),
        "joint_velocity_max_rad_s": peak_velocity.tolist(),
        "joint_acceleration_max_rad_s2": peak_acceleration.tolist(),
        "joint_limit_check_rate": "every physics substep after explicit initial equilibration",
        "time_quantization_max_s": max(abs(r["sim_time_s"]-r["execution_time_s"]) for r in rows),
        "object_displacement_m": float(np.linalg.norm(data.xpos[object_id]-start_object)),
        "rendered": renderer is not None, "render_error": render_error, "torque_limits": "asset actuator force saturation; feasibility not independently certified",
        "jerk_limits": "not_evaluated", "states": rows}
    (output / "simulation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

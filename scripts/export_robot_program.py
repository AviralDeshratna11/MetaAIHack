"""Turn a compiled robot trajectory into a controller-ready program, after a pre-flight check.

Output follows the shape of ROS 2 ``trajectory_msgs/JointTrajectory`` (joint names, points
with positions/velocities/accelerations/time_from_start) plus timed gripper commands for
``franka_gripper``. It is a file for a person to review and run under their own safety
procedures. Nothing here talks to a robot, and no trajectory from this repository has been
executed on hardware.

    python -m scripts.export_robot_program data/replication/<run>/robot_trajectory.json --speed 0.5
"""
import argparse
import json
from pathlib import Path

import numpy as np

# Franka Emika Panda / FR3 joint limits from the manufacturer's robot specification.
POSITION = {"panda": ([-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -.0175, -2.8973], [2.8973, 1.7628, 2.8973, -.0698, 2.8973, 3.7525, 2.8973]),
            "fr3": ([-2.7437, -1.7837, -2.9007, -3.0421, -2.8065, .5445, -3.0159], [2.7437, 1.7837, 2.9007, -.1518, 2.8065, 4.5169, 3.0159])}
VELOCITY = {"panda": [2.175, 2.175, 2.175, 2.175, 2.61, 2.61, 2.61], "fr3": [2.62, 2.62, 2.62, 2.62, 5.26, 4.18, 5.26]}
ACCELERATION = {"panda": [15, 7.5, 10, 12.5, 15, 20, 20], "fr3": [10, 10, 10, 10, 10, 10, 10]}


def preflight(trajectory, speed, margin):
    """Every reason this trajectory should not be sent to a controller as is."""
    robot = trajectory["robot"].get("robot_id", "panda")
    frames, problems = trajectory["frames"], []
    if not frames:
        return ["Trajectory is empty"], robot
    if any(not f["valid"] for f in frames):
        problems.append(f"{sum(not f['valid'] for f in frames)} planned frames failed kinematic checks: {sorted({r for f in frames for r in f['reasons']})}")
    if any(f["gripper_width_m"] is None for f in frames):
        problems.append("Gripper command is unknown in part of the trajectory")
    joints = np.array([f["joints_rad"] for f in frames])
    low, high = (np.array(v) for v in POSITION[robot])
    if np.any(joints < low+margin) or np.any(joints > high-margin):
        problems.append(f"Joint positions come within {margin} rad of a hardware limit")
    for name, key, limit in (("velocity", "velocity_rad_s", VELOCITY[robot]), ("acceleration", "acceleration_rad_s2", ACCELERATION[robot])):
        scale = speed if name == "velocity" else speed**2
        peak = np.abs(np.array([f[key] for f in frames])).max(0)*scale/np.array(limit)
        if peak.max() > .8:
            problems.append(f"Joint {name} reaches {peak.max():.0%} of the hardware limit at speed {speed}; keep it under 80%")
    times = np.array([f["execution_time_s"] for f in frames])
    if np.any(np.diff(times) <= 0):
        problems.append("Timestamps are not strictly increasing")
    if np.abs(np.diff(joints, axis=0)).max() > .2:
        problems.append("A joint jumps more than 0.2 rad between consecutive commands")
    return problems, robot


def program(trajectory, speed, robot):
    prefix = "fr3_joint" if robot == "fr3" else "panda_joint"
    frames = trajectory["frames"]
    points = [{"positions": f["joints_rad"], "velocities": [v*speed for v in f["velocity_rad_s"]],
               "accelerations": [a*speed**2 for a in f["acceleration_rad_s2"]], "time_from_start_s": f["execution_time_s"]/speed} for f in frames]
    gripper, previous = [], None
    for frame in frames:
        state = "open" if frame["gripper_state"] == "open" else "closed"
        if state != previous:
            command = {"time_from_start_s": frame["execution_time_s"]/speed, "phase": frame.get("phase")}
            if state == "open":
                command.update(action="franka_gripper/move", width_m=trajectory["config"]["open_width_m"], speed_m_s=.05)
            else:
                command.update(action="franka_gripper/grasp", width_m=trajectory["config"]["closed_width_m"], speed_m_s=.05, force_n=20,
                               epsilon_inner_m=.08, epsilon_outer_m=.08)
            gripper.append(command)
            previous = state
    scene = trajectory["config"].get("task_scene") or {}
    return {"format": "video2robot-robot-program-v1", "robot": robot, "source_run_id": trajectory["run_id"], "task": trajectory["task"],
        "speed_scale": speed, "duration_s": points[-1]["time_from_start_s"],
        "start_posture": {"joint_names": [f"{prefix}{i}" for i in range(1, 8)], "positions": frames[0]["joints_rad"],
                          "note": "Move here slowly with the robot's own planner before starting the trajectory"},
        "joint_trajectory": {"joint_names": [f"{prefix}{i}" for i in range(1, 8)], "points": points},
        "gripper_commands": gripper,
        "assumed_scene": {"note": "The trajectory was planned against this generated scene in the robot base frame. The real object must be "
                                  "placed and measured to match it, or the plan must be regenerated from a measured calibration.",
                          "task_scene": scene},
        "phases": trajectory["adaptation"].get("phases"),
        "executed_on_hardware": False,
        "operator_checklist": ["Confirm the real object's pose and size match assumed_scene, within the fingers' clearance",
            "Run first at reduced speed with the hand on the enabling device or emergency stop",
            "Use the controller's own collision thresholds and joint impedance; this file sets none",
            "The grasp force is a placeholder; set it for the real object"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trajectory", type=Path, help="robot_trajectory.json from a compiled run")
    parser.add_argument("--speed", type=float, default=.5, help="Time scaling: 0.5 runs at half the simulated speed")
    parser.add_argument("--margin", type=float, default=.05, help="Required distance from joint position limits (rad)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 < args.speed <= 1:
        parser.error("--speed must be in (0, 1]")
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    problems, robot = preflight(trajectory, args.speed, args.margin)
    if problems:
        print(json.dumps({"status": "refused", "problems": problems}, indent=2))
        raise SystemExit(1)
    target = args.output or args.trajectory.with_name("robot_program.json")
    result = program(trajectory, args.speed, robot)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "written", "output": target.as_posix(), "robot": robot, "points": len(result["joint_trajectory"]["points"]),
        "duration_s": round(result["duration_s"], 2), "gripper_commands": len(result["gripper_commands"]), "executed_on_hardware": False}, indent=2))


if __name__ == "__main__":
    main()

"""Strict offline RL transitions from actual simulated states.

Only row i -> i+1 is exported: the final command has no measured successor and is
excluded. End-of-recording is truncation, never fabricated task success.
"""
import json
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from packages.common.utils import file_hash


def export_transitions(trajectory, simulation, quality, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    frames, states = trajectory.frames, simulation.get("states", [])
    if len(frames) != len(states) or len(frames) < 2:
        raise ValueError("RL export requires at least two aligned measured states")
    if not simulation.get("physics_stepped"):
        raise ValueError("RL transitions require actual physics execution")
    if trajectory.config.task_scene is None:
        report = {"status": "blocked", "reason": "Explicit task and reward definition required", "transitions": 0}
        (output/"rl_report.json").write_text(json.dumps(report), encoding="utf-8")
        return report
    rows = []
    def obs(s):
        return s["joints_rad"]+[s["gripper_width_m"]]+s["joint_velocity_rad_s"]+s["tcp_position_m"]+s["proxy_object_position_m"]
    for i in range(len(frames)-1):
        a, b = states[i:i+2]; command = frames[i+1]
        if not command.valid or command.gripper_width_m is None or not frames[i].valid:
            raise ValueError(f"Invalid/unknown command at transition {i}")
        if abs(b['execution_time_s']-command.execution_time_s) > 1e-6:
            raise ValueError("Action/state time mismatch")
        task = b.get("task")
        if not task or not np.isfinite(task["reward"]): raise ValueError("Missing task reward")
        terminated = task["success"] is True
        rows.append({"episode_index": 0, "step_index": i, "timestamp": a["execution_time_s"],
            "source_time_s": frames[i].source_time_s, "duration_s": b["sim_time_s"]-a["sim_time_s"],
            "observation": obs(a), "action": command.joints_rad+[command.gripper_width_m],
            "next_observation": obs(b), "reward": task["reward"], "terminated": terminated,
            "truncated": i == len(frames)-2 and not terminated, "discount": 0. if terminated else 1.,
            "source_run_id": trajectory.source_run_id, "run_id": trajectory.run_id,
            "accepted_training_subset": quality.accepted_training_subset})
        if terminated: break
    if any(r['duration_s'] <= 0 or not np.isfinite(r['observation']+r['action']+r['next_observation']).all() for r in rows):
        raise ValueError("Nonfinite/nonmonotonic transitions")
    schema = pa.schema([('episode_index',pa.int64()),('step_index',pa.int64()),('timestamp',pa.float64()),
        ('source_time_s',pa.float64()),('duration_s',pa.float64()),('observation',pa.list_(pa.float32(),21)),
        ('action',pa.list_(pa.float32(),8)),('next_observation',pa.list_(pa.float32(),21)),('reward',pa.float64()),
        ('terminated',pa.bool_()),('truncated',pa.bool_()),('discount',pa.float64()),('source_run_id',pa.string()),
        ('run_id',pa.string()),('accepted_training_subset',pa.bool_())])
    path = output/'transitions.parquet'
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),path,compression='zstd')
    read = pq.read_table(path).to_pylist()
    if len(read) != len(rows) or read[-1]['terminated'] == read[-1]['truncated']:
        raise ValueError("Transition round-trip/episode end invalid")
    report = {"status":"completed", "format":"video2robot-transitions-v1", "transitions":len(rows),
        "roundtrip_passed":True, "sha256":file_hash(path), "action":"next-tick absolute joint radians[7], gripper width meters; linear interpolation controller",
        "observation":"joints[7], gripper width, joint velocities[7], TCP xyz[3], object xyz[3]",
        "reward":"configured simulation task shaping at successor state", "observation_source":"simulated",
        "terminal_semantics":"task success terminates; recording end truncates with discount 1",
        "source_task_validated":False, "accepted_training_subset":quality.accepted_training_subset,
        "simulation_only":True, "task":trajectory.config.task_scene.model_dump(mode='json')}
    report['initial_command_joints_rad'] = frames[0].joints_rad
    report['initial_gripper_width_m'] = frames[0].gripper_width_m
    report['control_hz'] = trajectory.config.control_hz
    (output/'rl_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

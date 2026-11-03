"""Real Panda/MuJoCo/official-LeRobot diagnostic; synthetic inputs, never live accuracy."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as N

import numpy as np

from packages.common.utils import file_hash
from packages.geometry.math3d import matrix_quaternion
from packages.robot.panda import Panda
from packages.robot.retarget import retarget
from packages.robot.simulation import replay
from packages.robot.exporter import export_isolated
from packages.robot.quality import classify
from packages.schemas.reconstruction import ContactFrame
from packages.schemas.robotization import Calibration, RobotizationConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", default="data/robots/franka_emika_panda")
    parser.add_argument("--lerobot-python", default=".venv-lerobot/Scripts/python.exe" if os.name == "nt" else ".venv-lerobot/bin/python")
    parser.add_argument("--output", default="data/phase3-smoke")
    parser.add_argument("--report", default="eval/reports/phase3-smoke.json")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    # A new directory makes immutable official dataset creation repeatable.
    root = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    started = time.monotonic()
    robot = Panda(args.assets)
    p, r = robot.fk(robot.home)
    frames = []
    for i in range(6):
        h = N(entity_id="hand", track_id="hand:0", pose=N(position_xyz=(p+[i*.003, 0, 0]).tolist()))
        obj = N(entity_id="object", track_id="object:0", pose=N(position_xyz=(p+[i*.003, 0, -.1]).tolist()))
        contacts = [ContactFrame(shot_id="shot", frame_index=i*3, timestamp=i*.2, hand_id="hand", object_id="object",
            state="NO_CONTACT", geometry_origin="sampled", evidence_origin="synthetic")]
        frames.append(N(shot_id="shot", world_frame="synthetic", frame_index=i*3, timestamp=i*.2,
                        hands=[h], objects=[obj], contacts=contacts))
    itr = N(video_id="synthetic-panda-diagnostic", run_id="synthetic-source", task="Synthetic diagnostic reach; no grasp", frames=frames,
            quality=N(review_reasons=["Synthetic input; not human reconstruction"], inference_mode="fixture"))
    config = RobotizationConfig(hand_id="hand", object_id="object", shot_id="shot", end_s=1.01,
        calibration=Calibration(mode="measured", residual_m=0, evidence="Synthetic coordinates constructed from official Panda FK"),
        tcp_quaternion_xyzw=matrix_quaternion(r), initial_gripper="open")
    trajectory = retarget(itr, config, robot, "phase3-diagnostic")
    (root / "robot_trajectory.json").write_text(trajectory.model_dump_json(indent=2), encoding="utf-8")
    simdir, exportdir = root / "simulation", root / "export"
    simdir.mkdir(); exportdir.mkdir()
    simulation = replay(trajectory, args.assets, simdir)
    export = export_isolated(str(Path(args.lerobot_python).absolute()), trajectory, simulation, exportdir)
    quality = classify(trajectory, simulation, export)
    report = {"status": "passed" if export["roundtrip_passed"] and export["images_decoded"] and simulation["rendered"] and simulation["physics_stepped"] and simulation["passed"] and all(f.valid for f in trajectory.frames) else "failed",
        "mode": "synthetic_inputs_real_robot_simulator_and_exporter", "elapsed_s": round(time.monotonic()-started, 3),
        "robot": robot.spec, "frames": len(trajectory.frames), "valid_frames": sum(f.valid for f in trajectory.frames),
        "simulation": {k: v for k, v in simulation.items() if k != "states"}, "export": export,
        "quality": quality.model_dump(mode="json"), "artifacts": {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()},
        "output": root.as_posix(), "live_models_executed": False}
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "artifacts"}, indent=2))
    if report["status"] != "passed": raise SystemExit(1)


if __name__ == "__main__":
    main()

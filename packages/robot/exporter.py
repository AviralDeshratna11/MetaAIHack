"""Subprocess boundary for official LeRobot 0.4.1 (v3) writer and reader."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from packages.common.utils import DomainError


def export_isolated(python, trajectory, simulation, output):
    output = Path(output)
    python = python or os.environ.get("LEROBOT_PYTHON", "")
    if not python:
        candidates = [Path(".venv-lerobot/Scripts/python.exe" if os.name == "nt" else ".venv-lerobot/bin/python")]
        python = next((str(p.absolute()) for p in candidates if p.is_file()), "")
    if not python:
        raise DomainError("E_EXPORT_RUNTIME", "Configure LEROBOT_PYTHON for the pinned dataset runtime", 503)
    request = output / "export_request.json"
    request.write_text(json.dumps({"trajectory": trajectory.model_dump(mode="json"), "simulation": simulation}), encoding="utf-8")
    completed = subprocess.run([python, "-m", "packages.robot.exporter", "--request", str(request.resolve()),
        "--output", str(output.resolve())], capture_output=True, timeout=900,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
             "HF_HOME": str(Path("data/runtime-cache/huggingface").resolve()),
             "HF_DATASETS_CACHE": str(Path("data/runtime-cache/datasets").resolve())})
    (output / "export_stdout.log").write_bytes(completed.stdout)
    (output / "export_stderr.log").write_bytes(completed.stderr)
    if completed.returncode:
        raise DomainError("E_EXPORT_RUNTIME", "Official dataset export failed; inspect export_stderr.log", 503)
    return json.loads((output / "export_report.json").read_text())


def official_export(request, output):
    import importlib.metadata
    import cv2
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    if importlib.metadata.version("lerobot") != "0.4.1":
        raise RuntimeError("Expected pinned lerobot==0.4.1")
    trajectory, simulation = request["trajectory"], request["simulation"]
    frames, states = trajectory["frames"], simulation["states"]
    if len(frames) != len(states) or not frames:
        raise RuntimeError("Simulation/command alignment is incomplete")
    if any(f["gripper_width_m"] is None for f in frames):
        raise RuntimeError("Unknown gripper commands cannot be exported as training actions")
    output = Path(output)
    root = output / "dataset"
    names = [f"joint{i}.rad" for i in range(1, 8)]+["gripper_width.m"]
    features = {"observation.state": {"dtype": "float32", "shape": (8,), "names": names},
                "action": {"dtype": "float32", "shape": (8,), "names": names}}
    # Simulator replay is the only robot image observation; never label human frames robot camera data.
    video = output.parent / "simulation" / "simulation_replay.mp4"
    capture = cv2.VideoCapture(str(video)) if video.is_file() else None
    if capture and capture.isOpened():
        features["observation.images.simulator"] = {"dtype": "video", "shape": (360, 640, 3), "names": ["height", "width", "channels"]}
    dataset = LeRobotDataset.create(repo_id="local/video2robot", fps=trajectory["config"]["control_hz"],
        root=root, features=features, robot_type="franka_panda_simulated", video_backend="pyav")
    for index, (frame, state) in enumerate(zip(frames, states)):
        if abs(frame["execution_time_s"]-state["execution_time_s"]) > 1e-6:
            raise RuntimeError("Command/state timestamps disagree")
        # State is sampled at the beginning of the command interval; action is its target.
        item = {"observation.state": np.array(state["joints_rad"]+[state["gripper_width_m"]], dtype=np.float32),
                "action": np.array(frame["joints_rad"]+[frame["gripper_width_m"]], dtype=np.float32), "task": trajectory["task"]}
        if "observation.images.simulator" in features:
            ok, image = capture.read()
            if not ok: raise RuntimeError("Replay video shorter than trajectory")
            item["observation.images.simulator"] = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        dataset.add_frame(item)
    if capture: capture.release()
    dataset.save_episode()
    dataset.finalize()
    del dataset
    reader = LeRobotDataset("local/video2robot", root=root, video_backend="pyav")
    if len(reader) != len(frames): raise RuntimeError("Dataset length changed")
    previous = -1
    for index in range(len(reader)):
        row = reader[index]
        t = float(row["timestamp"])
        if t <= previous or abs(t-index/trajectory["config"]["control_hz"]) > 1e-4:
            raise RuntimeError("Invalid dataset timestamps")
        previous = t
        for key in ("action", "observation.state"):
            if tuple(row[key].shape) != (8,) or not np.isfinite(row[key].numpy()).all():
                raise RuntimeError("Invalid dataset feature")
        expected = np.array(frames[index]["joints_rad"]+[frames[index]["gripper_width_m"]])
        if not np.allclose(row["action"].numpy(), expected, atol=1e-6):
            raise RuntimeError("Action round-trip or joint ordering mismatch")
        if "observation.images.simulator" in features and tuple(row["observation.images.simulator"].shape) != (3, 360, 640):
            raise RuntimeError("Image decoding mismatch")
    report = {"lerobot_version": "0.4.1", "format": "v3.0", "roundtrip_passed": True,
        "frames": len(reader), "episodes": 1, "images_decoded": "observation.images.simulator" in features,
        "state": "measured simulated joints/width at command interval start", "action": "absolute joint/width targets",
        "joint_order": names, "diagnostic_only": True, "accepted_training_subset": False,
        "source_run_id": trajectory["source_run_id"], "run_id": trajectory["run_id"]}
    (output / "export_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (root / "provenance.json").write_text(json.dumps({"run_id": trajectory["run_id"],
        "source_run_id": trajectory["source_run_id"], "adaptation": trajectory["adaptation"],
        "robot": trajectory["robot"], "review_reasons": trajectory["review_reasons"],
        "source_time_s": [f["source_time_s"] for f in frames]}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    official_export(json.loads(Path(args.request).read_text()), args.output)

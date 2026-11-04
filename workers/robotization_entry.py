"""CLI and callable CPU robot compiler. No fixture/model substitution."""
import argparse
import json
from pathlib import Path
from packages.common.utils import file_hash

from packages.robot.panda import Panda
from packages.robot.retarget import retarget
from packages.robot.simulation import replay
from packages.robot.quality import classify
from packages.robot.exporter import export_isolated
from packages.robot.rl import export_transitions
from packages.schemas.reconstruction import InteractionTrajectory
from packages.schemas.robotization import RobotizationConfig, RobotizationHandoff


def run(request, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    runtime = request["runtime"]
    if runtime.get("asset_manifest_sha256") and file_hash(Path(runtime["assets"]) / "asset_manifest.json") != runtime["asset_manifest_sha256"]:
        raise ValueError("Robot assets changed since submission")
    config = RobotizationConfig.model_validate(runtime["config"])
    itr = InteractionTrajectory.model_validate(request["itr"])
    robot = Panda(runtime["assets"])
    trajectory = retarget(itr, config, robot, request["run_id"])
    trajectory.review_reasons = sorted(set(trajectory.review_reasons+request["handoff"]["review_reasons"]))
    (output / "robot_trajectory.json").write_text(trajectory.model_dump_json(indent=2), encoding="utf-8")
    sim_dir = output / "simulation"
    sim_dir.mkdir()
    simulation = replay(trajectory, runtime["assets"], sim_dir)
    # Public API uses a flat report name; media and dataset stay in subdirectories.
    (output / "simulation_report.json").write_text(json.dumps(simulation, indent=2), encoding="utf-8")
    export_dir = output / "export"
    export_dir.mkdir()
    export = {"roundtrip_passed": False, "status": "not_requested"}
    if config.require_export:
        try:
            if not config.diagnostic_export and (trajectory.review_reasons or not all(f.valid for f in trajectory.frames)):
                raise ValueError("Unresolved trajectory requires explicit diagnostic_export")
            export = export_isolated(runtime["lerobot_python"], trajectory, simulation, export_dir)
        except Exception as exc:
            # Preserve useful IK/simulation diagnostics and fail the export gate.
            export = {"roundtrip_passed": False, "status": "failed", "reason": str(exc)}
    (output / "export_report.json").write_text(json.dumps(export, indent=2), encoding="utf-8")
    quality = classify(trajectory, simulation, export)
    (output / "quality_report.json").write_text(quality.model_dump_json(indent=2), encoding="utf-8")
    (output / "source_provenance.json").write_text(json.dumps(request.get("provenance",{
        "status":"not_supplied","reason":"Standalone diagnostic; not a queued source lineage"}),indent=2),encoding="utf-8")
    try:
        export_transitions(trajectory, simulation, quality, output/"rl")
    except ValueError as exc:
        directory = output/"rl"; directory.mkdir(exist_ok=True)
        (directory/"rl_report.json").write_text(json.dumps({"status":"blocked","reason":str(exc),"accepted_training_subset":False}),encoding="utf-8")
    from packages.robot.bundle import build_bundle
    if config.export_rlds:
        try:
            from packages.robot.rlds_exporter import export_isolated as export_rlds
            result=export_rlds(runtime.get('rlds_python'),output/'rl',output/'rlds')
            export['requested_formats_passed']=result['roundtrip_passed']
        except Exception as exc:
            directory=output/'rlds';directory.mkdir(exist_ok=True)
            (directory/'rlds_report.json').write_text(json.dumps({'roundtrip_passed':False,'reason':str(exc)}),encoding='utf-8')
            export['requested_formats_passed']=False
        quality=classify(trajectory,simulation,export)
        # Requested-format failure must also revoke any provisional RL eligibility.
        if export.get('requested_formats_passed') is False:
            try:export_transitions(trajectory,simulation,quality,output/'rl')
            except ValueError:pass  # Already recorded as blocked above.
        (output/'quality_report.json').write_text(quality.model_dump_json(indent=2),encoding='utf-8')
        (output/'export_report.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    build_bundle(output,trajectory,quality)
    handoff = RobotizationHandoff(video_id=itr.video_id, run_id=request["run_id"], source_run_id=itr.run_id,
        inference_mode=itr.quality.inference_mode, artifacts={}, quality=quality)
    (output / "phase3_handoff.json").write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
    return trajectory, simulation, export, quality


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(json.loads(Path(args.request).read_text()), args.output)

"""Recompute contact and IK variants on frozen artifacts; no new model requests."""
import argparse
import gzip
import json
import tempfile
import time
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from packages.robot.panda import Panda
from packages.robot.retarget import retarget
from packages.schemas.models import SemanticPlan, VideoManifest
from packages.schemas.reconstruction import ReconstructionConfig, InteractionTrajectory
from packages.schemas.robotization import RobotizationConfig
from workers.geometry.reconstruct import MaskReader
from workers.interaction.fusion import fuse_interactions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:58001")
    parser.add_argument("--source-report", default="eval/reports/phase2-reverification.json")
    parser.add_argument("--report", default="eval/reports/baseline-ablations.json")
    parser.add_argument("--assets", default="data/robots/franka_emika_panda")
    args = parser.parse_args()
    source = json.loads(Path(args.source_report).read_text())
    client = httpx.Client(timeout=120)
    r = client.get(f"{args.api}/v1/videos/{source['video_id']}/artifacts?run_id={source['run_id']}")
    r.raise_for_status()
    refs = r.json()["artifacts"]
    byname = {a["name"]: a for a in refs}
    bykey = {a["uri"]: a for a in refs}
    def read(key):
        r = client.get((byname.get(key) or bykey[key])["url"])
        r.raise_for_status(); return r.content
    results = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        def table(name):
            p = root / name; p.write_bytes(read(name)); return pq.read_table(p).to_pylist()
        manifest = VideoManifest.model_validate_json(read("manifest.json"))
        plan = SemanticPlan.model_validate_json(read("semantic_plan.json"))
        tracks, hands, objects = (table(name) for name in ("tracks.parquet", "hand_pose.parquet", "object_pose.parquet"))
        masks = MaskReader(read)
        variants = {"full": {}, "semantic_only": {"contact_mask_weight": 0, "contact_geometry_weight": 0, "contact_motion_weight": 0, "contact_semantic_weight": 1},
            "no_mask": {"contact_mask_weight": 0}, "no_geometry": {"contact_geometry_weight": 0},
            "no_motion": {"contact_motion_weight": 0}, "no_semantics": {"contact_semantic_weight": 0},
            "no_refinement": {"enable_boundary_refinement": False}}
        for name, changes in variants.items():
            cfg = ReconstructionConfig(**changes).model_dump()
            started = time.monotonic()
            report = fuse_interactions(manifest, plan, tracks, masks, hands, objects, root/name, cfg, source.get("inference_mode", "fixture"))
            refined = json.loads((root/name/"refined_actions.json").read_text())
            results.append({"variant": name, "config": cfg, "elapsed_s": round(time.monotonic()-started, 3),
                "contact_frames": report["contact_frames"], "events": report["contact_events"], "unknown_frames": report["unknown_frames"],
                "refined_starts": sum(a["refined_start_s"] is not None for a in refined),
                "accuracy": "not_evaluated; independent ground truth absent"})
        itr = InteractionTrajectory.model_validate_json(gzip.decompress(read("interaction_trajectory.json.gz")))
        observations = [f for f in itr.frames if any(p.pose for p in f.hands) and any(p.pose for p in f.objects)]
        a,b = next((a,b) for a,b in zip(observations, observations[1:]) if b.timestamp-a.timestamp <= 1)
        cfg = RobotizationConfig(hand_id=next(p.entity_id for p in a.hands if p.pose), object_id=next(p.entity_id for p in a.objects if p.pose),
            shot_id=a.shot_id, start_s=a.timestamp, end_s=b.timestamp+.001, max_gap_s=1, workspace_extent_m=.02, workspace_center_m=[.42,0,.55])
        for continuity in (False, True):
            started = time.monotonic()
            trajectory = retarget(itr, cfg, Panda(args.assets), "ablation", continuity=continuity)
            results.append({"variant": "continuous_collision_ik" if continuity else "basic_ik", "config": cfg.model_dump(mode="json"),
                "elapsed_s": round(time.monotonic()-started, 3), "frames": len(trajectory.frames),
                "kinematic_failed_frames": sum(bool(set(f.reasons)-{"GRIPPER_UNKNOWN"}) for f in trajectory.frames),
                "unknown_gripper_frames": sum(f.gripper_width_m is None for f in trajectory.frames),
                "max_position_error_m": max(f.position_error_m for f in trajectory.frames), "accuracy": "consistency diagnostic only"})
    report = {"status": "completed", "source_run_id": source["run_id"], "mode": source.get("inference_mode", "fixture"),
        "input_artifact_hashes": {a["name"]: a["sha256"] for a in refs}, "seed": 0, "real_model_calls": 0,
        "variants": results, "body_vs_geometry": "not_run; real body inference unavailable",
        "interpretation": "Frozen-input diagnostic experiment; no accuracy or causal generalization claims"}
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": "completed", "variants": len(results), "report": args.report}))


if __name__ == "__main__":
    main()

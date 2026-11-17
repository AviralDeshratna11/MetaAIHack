"""Skill replication: inference from demonstrations, generated scenes, planning and physics."""
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from packages.common.utils import DomainError
from packages.robot.articulated import Articulation
from packages.robot.skill import extract_skill
from packages.robot.synthetic import DEMOS, demonstration
from packages.robot.tasks import TaskEvaluator
from packages.schemas.replication import ArticulatedObject
from packages.schemas.robotization import Calibration, RobotizationConfig, TaskScene

ASSETS = "data/robots/franka_emika_panda"


def config(**changes):
    return RobotizationConfig(**{"hand_id": "HAND", "object_id": "OBJECT", "shot_id": "shot_000", "mode": "skill", "end_s": 100,
                              "initial_gripper": "open", **changes})


@pytest.mark.parametrize("name", sorted(DEMOS))
@pytest.mark.parametrize("seed", [0, 3, 7])
def test_skill_is_recovered_from_noisy_relative_scale_demonstrations(name, seed):
    itr, truth = demonstration(name, seed=seed)
    skill = extract_skill(itr, config())
    assert (skill.kind, skill.template, skill.direction) == (truth["kind"], truth["template"], truth["direction"])
    assert skill.motion_source == "hand_during_contact"
    if skill.kind == "static":
        # Nothing to measure: the plan names the action, so confidence is capped and it says why.
        assert skill.confidence == .5 and any("declared default" in r for r in skill.review_reasons)
        return
    assert skill.confidence > .5 and skill.progress[0] == 0 and skill.progress[-1] == 1
    if skill.kind == "revolute":
        assert abs(skill.displacement-truth["amount"]) < .25
    else:
        assert abs(skill.displacement-truth["amount"])/truth["amount"] < .15
    if skill.kind == "transport":
        assert skill.transport.released == truth["released"] and skill.transport.rise_units > 0
        assert skill.transport.heading_rad is not None


def test_skill_does_not_depend_on_scale_or_viewpoint():
    # Same process filmed from another heading and reconstructed at another scale.
    angles = [extract_skill(demonstration("laptop_lid", seed=seed, scale=scale, noise=.001)[0], config()).displacement
              for seed, scale in ((1, .4), (2, 2.7), (5, 9.))]
    assert np.ptp(angles) < .08 and abs(np.mean(angles)-1.75) < .08


def test_hinge_and_slide_ambiguity_is_reported_not_hidden():
    # Without an object name, a noisy line and a shallow arc are hard to tell apart.
    itr, _ = demonstration("drawer", seed=18, noise=.004, fps=5.)
    named = extract_skill(itr, config())
    assert named.kind == "prismatic"
    for entity in itr.entities:
        entity.semantic_name = entity.category = "thing"
    unnamed = extract_skill(itr, config())
    assert unnamed.confidence < .5 < named.confidence
    assert any("almost equally well" in r and "fit margin" in r for r in unnamed.review_reasons)


def free_motion():
    itr, _ = demonstration("drawer", seed=0)
    random = np.random.default_rng(4)
    for frame in itr.frames:
        frame.hands[0].pose.position_xyz = random.uniform(-1, 1, 3).tolist()
    return itr


def test_unsupported_motion_is_refused_with_guidance():
    from packages.robot.replicate import build_object, readiness
    skill = extract_skill(free_motion(), config())
    assert skill.kind == "unconstrained" and skill.template == "none" and skill.confidence == 0
    with pytest.raises(DomainError, match="trajectory mode"):
        build_object(skill, config())
    # A hand that stays put with nothing in the plan naming a press or a twist is not guessed at.
    still, _ = demonstration("press_button")
    still.refined_actions[0].primitive = "REACH"
    for entity in still.entities:
        entity.semantic_name = entity.category = "thing"
    idle = extract_skill(still, config())
    assert idle.kind == "static" and idle.template == "none"
    check = readiness(free_motion(), config())
    assert not check["ready_for_ik_attempt"] and "trajectory mode" in check["reasons"][0]
    assert readiness(demonstration("drawer")[0], config())["skill"]["template"] == "drawer"


def test_too_few_samples_and_missing_contact_evidence():
    itr, _ = demonstration("laptop_lid")
    with pytest.raises(DomainError, match="four hand pose samples"):
        extract_skill(itr, config(end_s=.3))
    for frame in itr.frames:
        frame.contacts = []
    skill = extract_skill(itr, config())
    assert skill.motion_source != "hand_during_contact" and any("contact evidence" in r for r in skill.review_reasons)


def test_scene_follows_demonstration_and_explicit_overrides():
    from packages.robot.replicate import build_object
    itr, _ = demonstration("close_lid")
    skill = extract_skill(itr, config())
    part, reasons = build_object(skill, config())
    assert part.template == "lid" and part.start > 1 and part.goal == 0 and part.scale_source == "template_default"
    forced, reasons = build_object(skill, config(replication={"direction": "open", "template": "door"}))
    assert forced.template == "door" and forced.start == 0 and forced.goal > 1 and any("explicitly" in r for r in reasons)
    # Metric travel needs measured calibration; otherwise a declared default is used.
    drawer = extract_skill(demonstration("drawer")[0], config())
    default, reasons = build_object(drawer, config())
    assert default.goal == .15 and any("not metric" in r for r in reasons)
    measured, _ = build_object(drawer, config(calibration=Calibration(mode="measured", scale_m_per_unit=.2, residual_m=.001, evidence="tape measure")))
    assert measured.scale_source == "measured_calibration" and abs(measured.goal-drawer.displacement*.2) < 1e-9


def test_contracts_reject_inconsistent_articulation():
    part = dict(template="lid", joint="revolute", position_m=[.5, 0, .3], goal=1., limit=1.3, tolerance=.1, scale_source="template_default")
    with pytest.raises(ValidationError):
        ArticulatedObject(**{**part, "joint": "prismatic"})
    with pytest.raises(ValidationError):
        ArticulatedObject(**{**part, "goal": 2.})
    with pytest.raises(ValidationError):
        ArticulatedObject(**{**part, "goal": .05})
    with pytest.raises(ValidationError):
        TaskScene(task="articulated", evidence="x", goal_position_m=[0, 0, 0])
    with pytest.raises(ValidationError):
        TaskScene(task="reach", evidence="x", goal_position_m=[.5, 0, .3], articulation=ArticulatedObject(**part))


def test_handle_kinematics_keep_finger_axis_on_the_motion_tangent():
    for template, joint in (("lid", "revolute"), ("door", "revolute"), ("drawer", "prismatic")):  # parts whose handle travels
        part = ArticulatedObject(template=template, joint=joint, position_m=[.5, .1, .3], yaw_rad=.7, goal=.2, limit=.5,
                                 tolerance=.02, scale_source="template_default")
        articulation = Articulation(part)
        for q in (0., .1, .2):
            position, approach, tangent = articulation.handle(q)
            ahead, _, _ = articulation.handle(q+1e-5)
            assert np.allclose((ahead-position)/np.linalg.norm(ahead-position), tangent, atol=1e-3)
            rotation = articulation.grasp_rotation(q)
            assert np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-9) and np.isclose(np.linalg.det(rotation), 1)
            assert np.allclose(rotation[:, 1], tangent) and np.allclose(rotation[:, 2], approach) and abs(approach @ tangent) < 1e-9


def test_articulated_success_requires_goal_release_and_persistence():
    part = ArticulatedObject(template="drawer", joint="prismatic", position_m=[.5, 0, .3], goal=.15, limit=.19, tolerance=.02,
                             scale_source="template_default")
    scene = TaskScene(task="articulated", evidence="test", goal_position_m=[.35, 0, .3], articulation=part, success_hold_s=.2)
    evaluator = TaskEvaluator(scene)
    handle, away = np.array([.35, 0, .3]), np.array([.35, 0, .4])
    assert not evaluator.evaluate(handle, handle, .01, .1, (), .15)["success"]  # still gripping
    assert not evaluator.evaluate(away, handle, .08, .1, (), .05)["success"]  # released short of the goal
    assert not evaluator.evaluate(away, handle, .08, .1, (), .15)["success"]  # not yet held long enough
    held = evaluator.evaluate(away, handle, .08, .1, (), .15)
    assert held["success"] and held["joint_progress"] == 1 and held["source_task_validated"] is False
    assert not evaluator.evaluate(away, handle, .08, .1, {"COLLISION"}, .15)["success"]
    with pytest.raises(ValueError, match="joint value"):
        evaluator.evaluate(away, handle, .08, .1)


def test_replay_video_falls_back_when_no_encoder(tmp_path, monkeypatch):
    from packages.robot import video
    monkeypatch.setattr(video, "ffmpeg_binary", lambda: None)
    target = tmp_path/"replay.mp4"
    target.write_bytes(b"original")
    result = video.browser_playable(target)
    assert result["browser_playable"] is False and result["codec"] == "mp4v" and target.read_bytes() == b"original"


@pytest.fixture(scope="module")
def panda():
    pytest.importorskip("mujoco")
    pytest.importorskip("scipy")
    if not Path(ASSETS, "asset_manifest.json").is_file():
        pytest.skip("Official Panda assets not downloaded")
    from packages.robot.panda import Panda
    return Panda(ASSETS)


def test_transport_task_keeps_proportions_and_heading_not_coordinates():
    from packages.robot.replicate import build_task
    skill = extract_skill(demonstration("pick_place")[0], config())
    task, reasons = build_task(skill, config())
    move = np.array(task.displacement_m)
    assert task.release and task.scale_source == "template_default" and any("not metric" in r for r in reasons)
    # The demonstration carried 0.20 across and 0.06 up: the ratio survives, the size is declared.
    assert abs(np.hypot(*move[:2])-.15) < .02 and abs(move[2]/np.hypot(*move[:2])-.3) < .08
    assert abs(abs(np.arctan2(move[1], move[0]))-np.pi/2) < .35  # carried sideways relative to the reach
    scaled, notes = build_task(skill, config(), {"scale_m_per_unit": .37, "source": "body_scale_estimate"})
    assert scaled.scale_source == "body_scale_estimate" and abs(np.hypot(*scaled.displacement_m[:2])-.2) < .02
    assert any("estimate" in r for r in notes)
    held, _ = build_task(extract_skill(demonstration("pick_up")[0], config()), config())
    assert not held.release and held.displacement_m[2] >= .04


def test_video_scale_estimate_prefers_body_alignments_and_reports_spread():
    from packages.robot.metric import estimate_scale
    fits = [{"alignment_id": f"body-{i}-HAND-right", "scale": s} for i, s in enumerate((2.6, 2.7, 2.8))]
    fits.append({"alignment_id": "window-3", "scale": 9.})  # window alignments are not body scale
    estimate = estimate_scale(fits, [], "HAND")
    assert estimate["source"] == "body_scale_estimate" and abs(estimate["scale_m_per_unit"]-1/2.7) < 1e-9 and estimate["samples"] == 3
    random = np.random.default_rng(0)
    hand = [{"entity_id": "HAND", "pose": {}, "points_world": (random.uniform(-.5, .5, (200, 3))*[.46, .1, .05]).tolist()} for _ in range(3)]
    coarse = estimate_scale([], hand, "HAND")
    assert coarse["source"] == "hand_extent_estimate" and .3 < coarse["scale_m_per_unit"] < .5
    assert estimate_scale([], [], "HAND") is None and estimate_scale(fits[:1], [], "HAND") is None


def calibrated_drawer():
    itr, _ = demonstration("drawer", noise=.0005)
    # A calibration that puts the drawer handle at a chosen robot-base pose, opening along -x.
    points = np.array([f.hands[0].pose.position_xyz for f in itr.frames])
    contact = np.array([f.contacts[0].state == "CONTACT" for f in itr.frames])
    start, end = points[contact][0], points[contact][-1]
    forward = (end-start)/np.linalg.norm(end-start)
    up = np.array([0, -1., 0])
    out = -forward-(-forward @ up)*up
    out /= np.linalg.norm(out)
    rotation = np.vstack([out, np.cross(up, out), up])  # world -> base axes
    scale = .2/np.linalg.norm(end-start)
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation, np.array([.56, .02, .31])-scale*rotation @ start
    return itr, config(calibration=Calibration(mode="measured", scale_m_per_unit=scale, base_from_world=transform.tolist(), residual_m=.002, evidence="marker board"))


def test_measured_calibration_places_the_object_where_the_video_had_it():
    from packages.robot.replicate import build_task, measured_pose
    itr, cfg = calibrated_drawer()
    skill = extract_skill(itr, cfg)
    part, _ = build_task(skill, cfg)
    position, yaw = measured_pose(skill, cfg, part)
    assert np.allclose(position, [.56, .02, .31], atol=.01) and abs(abs(yaw)-np.pi) < .05 and abs(part.goal-.2) < .01
    assert part.scale_source == "measured_calibration"
    assert measured_pose(skill, config(), part) is None  # no calibration, no claim about placement


def test_measured_placement_is_used_when_reachable_and_replaced_when_not(panda):
    from packages.robot.replicate import replicate
    itr, cfg = calibrated_drawer()
    trajectory, _, part, placement = replicate(itr, cfg, panda, "measured")
    assert placement == "placement measured from the video" and part.placement_source == "measured_calibration"
    assert np.allclose(part.position_m, [.56, .02, .31], atol=.01) and all(f.valid for f in trajectory.frames)
    # The same demonstration calibrated two meters away cannot be reached: say so and fall back.
    far = np.array(cfg.calibration.base_from_world)
    far[0, 3] += 2
    distant = cfg.model_copy(update={"calibration": cfg.calibration.model_copy(update={"base_from_world": far.tolist()})})
    trajectory, _, part, placement = replicate(itr, distant, panda, "far")
    assert part.placement_source == "canonical" and "canonical" in placement
    assert any("not reachable" in r for r in trajectory.review_reasons)


@pytest.mark.parametrize("name", ["laptop_lid", "drawer", "close_drawer", "pick_place", "pick_up", "press_button", "turn_knob"])
def test_replication_succeeds_in_real_physics(panda, tmp_path, name):
    from packages.robot.replicate import replicate
    from packages.robot.simulation import replay
    itr, _ = demonstration(name)
    trajectory, skill, part, _ = replicate(itr, config(), panda, "test")
    assert all(f.valid and f.origin == "planned" for f in trajectory.frames)
    expected = {"pick_up": ["approach", "reach", "grasp", "manipulate", "hold"], "press_button": ["approach", "reach", "manipulate", "settle", "retreat", "hold"]}
    assert [p["phase"] for p in trajectory.adaptation["phases"]] == expected.get(name, ["approach", "reach", "grasp", "manipulate", "settle", "release", "retreat", "hold"])
    assert all(np.max(np.abs(f.velocity_rad_s)/panda.velocity) <= .31 for f in trajectory.frames)
    times = [f.source_time_s for f in trajectory.frames]
    assert times == sorted(times) and times[0] == itr.frames[0].timestamp and abs(times[-1]-itr.frames[-1].timestamp) < 1e-6
    report = replay(trajectory, ASSETS, tmp_path, render=False)
    assert report["passed"] and report["simulation_task_success"] and not report["violations"]
    assert report["source_task_validated"] is False and report["task_scene_validated"] is False and report["grasp_attachment"] is False
    if name in ("pick_place", "pick_up"):
        # The box is held by finger friction alone and ends where the carry was planned to end.
        assert abs(report["object_displacement_m"]-np.linalg.norm(part.displacement_m)) <= part.tolerance_m
        final = report["states"][-1]
        assert (final["gripper_width_m"] < .06) == (name == "pick_up") and final["task"]["released"] == (name == "pick_place")
    elif name == "press_button":
        assert report["task_joint"]["peak"] >= part.goal-part.tolerance and abs(report["task_joint"]["final"]) < .002  # pressed, then sprang back
    else:
        assert abs(report["task_joint"]["final"]-part.goal) <= part.tolerance


def test_moved_object_changes_the_motion_but_not_the_outcome(panda):
    from packages.robot.replicate import plan, replicate, variations
    itr, _ = demonstration("drawer")
    cfg = config(replication={"variations": 2, "variation_seed": 3})
    trajectory, skill, part, _ = replicate(itr, cfg, panda, "base")
    moved = part.model_copy(update={"position_m": [part.position_m[0]-.04, part.position_m[1]+.06, part.position_m[2]+.03], "yaw_rad": part.yaw_rad+.2})
    other = plan(skill, moved, cfg, panda, "moved", itr)
    grasp = lambda t: next(np.array(f.target_position_m) for f in t.frames if f.phase == "grasp")
    assert np.linalg.norm(grasp(trajectory)-grasp(other)) > .05  # absolute coordinates were not replayed
    results = variations(skill, part, cfg, panda, ASSETS, "base", itr)
    assert len(results) == 2 and all(r.planned and r.success and not r.violations for r in results)
    assert len({tuple(r.position_m) for r in results}) == 2
    carry, carried, task, _ = replicate(demonstration("pick_place")[0], cfg, panda, "carry")
    moved = variations(carried, task, cfg, panda, ASSETS, "carry", demonstration("pick_place")[0])
    assert all(r.planned and r.success for r in moved) and len({round(r.yaw_rad, 4) for r in moved}) == 2


def test_unreachable_placement_is_an_explicit_error(panda):
    from packages.robot.replicate import replicate
    itr, _ = demonstration("drawer")
    with pytest.raises(DomainError) as error:
        replicate(itr, config(replication={"object_position_m": [1.4, 0, .3]}), panda, "far")
    assert error.value.code == "E_SKILL_UNREACHABLE" and "out of reach" in error.value.message


def test_worker_entry_writes_skill_artifacts_and_learning_data(panda, tmp_path):
    from workers.robotization_entry import run
    itr, _ = demonstration("drawer")
    cfg = config(require_export=False, replication={"variations": 1})
    request = {"itr": itr.model_dump(mode="json"), "handoff": {"review_reasons": ["upstream note"]}, "run_id": "entry",
               "runtime": {"config": cfg.model_dump(mode="json"), "assets": ASSETS, "lerobot_python": ""}}
    trajectory, simulation, export, quality = run(request, tmp_path)
    report = json.loads((tmp_path/"replication_report.json").read_text())
    assert report["simulation_task_success"] and report["variation_success_rate"] == 1 and report["physical_robot_ready"] is False
    assert .9 < report["replicated_fraction"] < 1.1 and "upstream note" in trajectory.review_reasons
    assert json.loads((tmp_path/"skill_model.json").read_text())["template"] == "drawer"
    assert trajectory.config.task_scene.task == "articulated" and simulation["video"]["codec"] in ("h264", "mp4v")
    rl = json.loads((tmp_path/"rl"/"rl_report.json").read_text())
    assert rl["status"] == "completed" and rl["transitions"] > 100 and rl["task"]["articulation"]["template"] == "drawer"
    manifest = json.loads((tmp_path/"learning_manifest.json").read_text())
    assert {"skill_model.json", "replication_report.json", "simulation/simulation_replay.mp4"} <= manifest["files"].keys()
    # Synthetic input can never be promoted, whatever the simulator shows.
    assert quality.classification == "Reject" and not quality.accepted_training_subset and quality.checks["task_success"] is True


def test_skill_proposal_picks_the_supported_pair():
    from packages.robot.proposal import suggest_skill
    result = suggest_skill(demonstration("door")[0])
    assert result["available"] and result["config"]["mode"] == "skill" and result["skill"]["template"] == "door"
    assert result["config"]["hand_id"] == "HAND" and result["requires_review"]
    assert not suggest_skill(free_motion())["available"]


def test_isolated_runtime_reports_the_domain_reason(panda, tmp_path):
    # The queued worker deletes the runtime directory; the reason must survive as data.
    import subprocess
    import sys
    itr, _ = demonstration("drawer")
    cfg = config(require_export=False, replication={"object_position_m": [1.4, 0, .3]})
    request = tmp_path/"request.json"
    request.write_text(json.dumps({"itr": itr.model_dump(mode="json"), "handoff": {"review_reasons": []}, "run_id": "isolated",
        "runtime": {"config": cfg.model_dump(mode="json"), "assets": ASSETS, "lerobot_python": ""}}), encoding="utf-8")
    output = tmp_path/"output"
    completed = subprocess.run([sys.executable, "-m", "workers.robotization_entry", "--request", str(request), "--output", str(output)],
                               capture_output=True, timeout=300)
    failure = json.loads((output/"error.json").read_text())
    assert completed.returncode and failure["code"] == "E_SKILL_UNREACHABLE" and failure["status"] == 409 and "out of reach" in failure["message"]


def test_replication_results_are_part_of_the_api_contract(database):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
        assert {"/v1/videos/{video_id}/replication-report", "/v1/videos/{video_id}/skill-model"} <= spec["paths"].keys()
        assert {"ReplicationReport", "SkillModel", "ArticulatedObject"} <= spec["components"]["schemas"].keys()
        assert client.get("/v1/videos/missing/replication-report", params={"run_id": "none"}).status_code == 404
        payload = {"source_job_id": "missing", "idempotency_key": "k", "config": {"hand_id": "h", "object_id": "o", "shot_id": "s", "mode": "skill"}}
        assert client.post("/v1/videos/missing/robotize", json=payload).status_code == 404
        payload["config"]["mode"] = "teleport"
        assert client.post("/v1/videos/missing/robotize", json=payload).status_code == 422


def track_rows(entity, candidate, xs, status="ambiguous"):
    return [{"shot_id": "shot_000", "entity_id": entity, "provider_track_id": candidate, "frame_index": i, "timestamp": i/10,
             "observed": True, "centroid_normalized": [x, .5], "bbox_xyxy": [0, 0, 10+i, 10], "identity_status": status} for i, x in enumerate(xs)]


def test_automatic_association_uses_motion_roles_and_abstains_when_unclear():
    from workers.perception.associate import propose
    plan = {"entities": [{"entity_id": "mover", "semantic_name": "closing hand", "motion": "manipulated", "sam_prompt": "hand"},
                         {"entity_id": "holder", "semantic_name": "supporting hand", "motion": "static", "sam_prompt": "hand"},
                         {"entity_id": "laptop", "semantic_name": "laptop", "motion": "manipulated", "sam_prompt": "laptop"}],
            "actions": [{"actor": "mover", "primitive": "CLOSE", "start_s": .5, "end_s": 2.5}, {"actor": "holder", "primitive": "PRESS", "start_s": 0, "end_s": 3}]}
    still, moving = [.2+.001*(i % 2) for i in range(30)], [.5+.012*i for i in range(30)]
    tracks = [row for entity in ("mover", "holder") for row in track_rows(entity, "0", still)+track_rows(entity, "1", moving)]
    tracks += track_rows("laptop", "0", moving, "associated")
    proposals, reasons = propose(tracks, plan)
    assert {p["entity_id"]: p["provider_track_id"] for p in proposals} == {"mover": "1", "holder": "0"} and not reasons
    assert all(p["reviewed_by"] == "heuristic" and "Not human reviewed" in p["evidence"] and p["kind"] == "association" for p in proposals)
    # Two hands that move alike cannot be told apart by role: nothing is proposed.
    alike = [row for entity in ("mover", "holder") for row in track_rows(entity, "0", moving)+track_rows(entity, "1", [x+.2 for x in moving])]
    proposals, reasons = propose(alike, plan)
    assert not proposals and "not separated" in reasons[0]
    for entity in plan["entities"]:
        entity["motion"] = "unknown"
    assert propose(tracks, plan)[0] == []


def test_plan_filters_actions_by_actor_so_a_holding_hand_is_not_a_press():
    from packages.robot.proposal import suggest_skill
    itr, _ = demonstration("press_button")
    acting = {"actions": [{"actor": "HAND", "object": "OBJECT", "primitive": "PRESS", "start_s": 0, "end_s": 3}]}
    other = {"actions": [{"actor": "OTHER_HAND", "object": "OBJECT", "primitive": "PRESS", "start_s": 0, "end_s": 3}]}
    for entity in itr.entities:
        entity.semantic_name = entity.category = "thing"
    assert extract_skill(itr, config(), acting).template == "button"
    assert extract_skill(itr, config(), other).template == "none"
    # Among candidates, measured motion outranks a resting hand named by the plan.
    lid, _ = demonstration("close_lid")
    assert suggest_skill(lid)["skill"]["kind"] == "revolute"


def test_robot_program_export_checks_limits_and_never_claims_hardware(panda):
    from packages.robot.replicate import replicate
    from scripts.export_robot_program import preflight, program
    trajectory, _, _, _ = replicate(demonstration("drawer")[0], config(), panda, "program")
    data = trajectory.model_dump(mode="json")
    problems, robot = preflight(data, .5, .05)
    assert not problems and robot == "panda"
    result = program(data, .5, robot)
    points = result["joint_trajectory"]["points"]
    assert result["executed_on_hardware"] is False and result["joint_trajectory"]["joint_names"][0] == "panda_joint1"
    assert abs(points[-1]["time_from_start_s"]-2*data["frames"][-1]["execution_time_s"]) < 1e-9  # half speed, twice the time
    assert [c["action"].split("/")[1] for c in result["gripper_commands"]] == ["move", "grasp", "move"]
    data["frames"][10]["joints_rad"][3] = 0.  # beyond the elbow's hardware range
    data["frames"][20]["valid"], data["frames"][20]["reasons"] = False, ["SELF_COLLISION"]
    problems, _ = preflight(data, .5, .05)
    assert any("hardware limit" in p for p in problems) and any("SELF_COLLISION" in p for p in problems) and any("jumps" in p for p in problems)


def test_association_stitches_relabelled_tracks_and_uses_side_and_proximity():
    from workers.perception.associate import propose
    hand = {"entity_id": "hand", "semantic_name": "hand opening door", "motion": "manipulated", "sam_prompt": "hand"}
    # One hand the tracker lost and found again: its two ids never coexist.
    early = [r for r in track_rows("hand", "0", [.3]*30) if r["frame_index"] < 12]
    late = [r for r in track_rows("hand", "1", [.4]*30) if r["frame_index"] >= 12]
    proposals, reasons = propose(early+late, {"entities": [hand], "actions": []})
    assert proposals[0]["provider_track_ids"] == ["0", "1"] and "seen in turn" in proposals[0]["evidence"] and not reasons
    # Two hands that move alike but are named by the side of the frame they are on.
    sides = {"entities": [{**hand, "entity_id": "a", "semantic_name": "left-side hand grasping box"},
                          {**hand, "entity_id": "b", "semantic_name": "right-side hand grasping box"},
                          {"entity_id": "box", "semantic_name": "gift box", "motion": "static", "sam_prompt": "box"}],
             "actions": [{"actor": e, "object": "box", "primitive": "OPEN", "start_s": 0, "end_s": 3} for e in ("a", "b")]}
    wobble = lambda x: [x+.01*(i % 3) for i in range(30)]
    tracks = [row for e in ("a", "b") for row in track_rows(e, "0", wobble(.7))+track_rows(e, "1", wobble(.3))]
    # A box sharing provider ids "0"/"1" with the hands must not be grouped with them.
    tracks += [r for r in track_rows("box", "0", [.5]*30) if r["frame_index"] < 15]+[r for r in track_rows("box", "1", [.5]*30) if r["frame_index"] >= 15]
    proposals, reasons = propose(tracks, sides)
    picked = {p["entity_id"]: p.get("provider_track_ids", [p["provider_track_id"]]) for p in proposals}
    assert picked == {"a": ["1"], "b": ["0"], "box": ["0", "1"]} and not reasons
    # Two coexisting look-alike doors: the one the associated hand stays near is the one opened.
    doors = {"entities": [hand, {"entity_id": "door", "semantic_name": "cabinet door", "motion": "manipulated", "sam_prompt": "cabinet door"}],
             "actions": [{"actor": "hand", "object": "door", "primitive": "OPEN", "start_s": 0, "end_s": 3}]}
    tracks = track_rows("hand", "0", [.5]*30, "associated")+track_rows("door", "0", [.52]*30)+track_rows("door", "1", [.9]*30)
    proposals, reasons = propose(tracks, doors)
    assert [(p["entity_id"], p["provider_track_id"]) for p in proposals] == [("door", "0")] and "hand proximity" in proposals[0]["evidence"]
    far = track_rows("hand", "0", [.5]*30, "associated")+track_rows("door", "0", [.2]*30)+track_rows("door", "1", [.8]*30)
    assert propose(far, doors)[0] == [] and "hand proximity" in propose(far, doors)[1][0]


def test_stitched_identity_is_tracked_as_one_entity():
    from types import SimpleNamespace as N
    from workers.perception.tracking import build_tracklets
    mask = np.zeros((4, 6), bool)
    mask[1:3, 1:3] = True
    records = [{"frame": f, "object_id": "0" if f < 3 else "1", "mask": mask, "confidence": .9} for f in range(6)]
    shot, manifest = N(shot_id="shot_000", start_frame=0, end_frame=6), N(height=4, width=6, fps_den=1, fps_num=15)
    entity = N(entity_id="hand")
    frame_map = [{"source_timestamp": f/15} for f in range(6)]
    plain, _, _ = build_tracklets(records, entity, shot, manifest, frame_map, "v", "m", "ref")
    assert not any(r["identity_status"] == "associated" for r in plain)
    correction = {"kind": "association", "provider_track_id": "0", "provider_track_ids": ["0", "1"], "frame_index": 0}
    stitched, _, _ = build_tracklets(records, entity, shot, manifest, frame_map, "v", "m", "ref", correction)
    seen = sorted(r["frame_index"] for r in stitched if r["observed"] and r["identity_status"] == "associated")
    assert seen == list(range(6))


def test_plan_interval_replaces_missing_contact_evidence():
    itr, truth = demonstration("drawer")
    for frame in itr.frames:
        frame.contacts = []
    plan = {"actions": [{"actor": "HAND", "object": "OBJECT", "primitive": "REACH", "start_s": 0, "end_s": .9},
                        {"actor": "HAND", "object": "OBJECT", "primitive": "PULL", "start_s": .9, "end_s": 2.5},
                        {"actor": "OTHER", "object": "OBJECT", "primitive": "PULL", "start_s": 1., "end_s": 2.}]}
    skill = extract_skill(itr, config(), plan)
    assert skill.motion_source == "hand_during_planned_action" and (skill.kind, skill.direction) == ("prismatic", "open")
    assert abs(skill.displacement-truth["amount"])/truth["amount"] < .15
    assert any("action interval" in r for r in skill.review_reasons) and any("Another hand (OTHER)" in r for r in skill.review_reasons)


def test_geometry_uses_the_seen_row_of_a_stitched_identity_and_rejects_coexisting_ones():
    from workers.geometry.reconstruct import selected_tracks
    row = lambda frame, track, seen, status="associated": {"frame_index": frame, "entity_id": "hand", "track_id": track, "observed": seen, "identity_status": status if seen else "lost"}
    stitched = [row(0, "a", True), row(0, "b", False), row(1, "a", False), row(1, "b", True)]
    assert {k: v["track_id"] for k, v in selected_tracks(stitched).items()} == {(0, "hand"): "a", (1, "hand"): "b"}
    assert selected_tracks([row(0, "a", True), row(0, "b", True)]) == {}
    assert selected_tracks([row(0, "a", True, "ambiguous")]) == {}


def test_plan_overrides_the_up_hint_for_a_lid_but_not_a_measured_pull():
    lid, _ = demonstration("laptop_lid")
    says_close = {"actions": [{"actor": "HAND", "object": "OBJECT", "primitive": "CLOSE", "start_s": 0, "end_s": 3}]}
    skill = extract_skill(lid, config(), says_close)
    assert skill.direction == "close" and any("camera's up is only assumed" in r for r in skill.review_reasons)
    drawer, _ = demonstration("drawer")
    kept = extract_skill(drawer, config(), {"actions": [{"actor": "HAND", "object": "OBJECT", "primitive": "PUSH", "start_s": 0, "end_s": 3}]})
    assert kept.direction == "open" and any("geometry was kept" in r for r in kept.review_reasons)

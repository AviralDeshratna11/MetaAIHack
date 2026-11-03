from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from packages.robot.quality import classify
from packages.robot.retarget import gripper_transition
from packages.schemas.reconstruction import ContactFrame
from packages.schemas.robotization import Calibration, RobotizationConfig


def test_calibration_rejects_nonrigid_and_unsubstantiated_metric():
    with pytest.raises(ValidationError):
        Calibration(mode="measured", evidence="unknown")
    with pytest.raises(ValidationError):
        Calibration(evidence="bad", base_from_world=np.diag([2, 1, 1, 1]).tolist())
    with pytest.raises(ValidationError):
        RobotizationConfig(hand_id="h", object_id="o", shot_id="s", tcp_quaternion_xyzw=[1, 1, 0, 0])


def contact(state="UNKNOWN", origin="missing", motion=None):
    return ContactFrame(shot_id="s", frame_index=0, timestamp=0, hand_id="h", object_id="o", state=state,
                        geometry_origin=origin, evidence_origin="estimated" if origin != "missing" else "missing", motion_coupling=motion)


def test_gripper_missing_not_release_and_semantics_not_grasp():
    assert gripper_transition("closed", [contact()]) == "unknown"
    assert gripper_transition("open", [contact("CONTACT", "sampled", .1)]) == "unknown"
    assert gripper_transition("open", [contact("CONTACT", "sampled", .8)]) == "closed"
    assert gripper_transition("closed", [contact("NO_CONTACT", "held")]) == "closed"
    assert gripper_transition("closed", [contact("NO_CONTACT", "sampled")]) == "open"
    assert gripper_transition("open", [contact(), contact()]) == "unknown"


def test_robot_api_contract_and_invalid_source(database):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        payload = {"source_job_id": "missing", "idempotency_key": "test",
                   "config": {"hand_id": "h", "object_id": "o", "shot_id": "s"}}
        response = client.post("/v1/videos/missing/robotize", json=payload)
        assert response.status_code == 404
        spec = client.get("/openapi.json").json()
        assert "RobotizationHandoff" in spec["components"]["schemas"]
        assert "/v1/videos/{video_id}/robot-quality" in spec["paths"]


def test_quality_unknown_gates_cannot_pass_gold():
    from types import SimpleNamespace as N
    trajectory = N(inference_mode="live", frames=[N(valid=True)], review_reasons=[],
                   config=N(calibration=N(mode="measured")))
    simulation = {"physics_stepped": True, "passed": True, "task_scene_validated": True, "task_success": None}
    result = classify(trajectory, simulation, {"roundtrip_passed": True})
    assert result.classification == "Silver" and not result.accepted_training_subset
    simulation["task_success"] = True
    assert classify(trajectory, simulation, {"roundtrip_passed": True}).classification == "Gold"
    simulation["passed"] = False
    assert classify(trajectory, simulation, {"roundtrip_passed": True}).classification == "Reject"


@pytest.fixture
def panda():
    pytest.importorskip("mujoco")
    pytest.importorskip("scipy")
    if not Path("data/robots/franka_emika_panda/asset_manifest.json").is_file():
        pytest.skip("Official Panda assets not downloaded")
    from packages.robot.panda import Panda
    return Panda("data/robots/franka_emika_panda")


def test_actual_panda_fk_ik_and_unreachable(panda):
    p, r = panda.fk(panda.home)
    q, pe, re, collisions = panda.ik(p, r, panda.home)
    assert pe < 1e-5 and re < 1e-5 and not collisions
    assert np.allclose(q, panda.home)
    _, pe, _, _ = panda.ik(np.array([5, 5, 5]), r, panda.home)
    assert pe > 1


def make_itr(panda):
    from types import SimpleNamespace as N
    p, _ = panda.fk(panda.home)
    frames = []
    for index in range(4):
        pose = N(position_xyz=(p+np.array([.005*index, 0, 0])).tolist())
        h = N(entity_id="h", track_id="hand", pose=pose)
        o = N(entity_id="o", track_id="object", pose=pose)
        c = contact("NO_CONTACT", "sampled")
        frames.append(N(shot_id="s", world_frame="w", timestamp=index*.2, frame_index=index*3, hands=[h], objects=[o], contacts=[c]))
    return N(video_id="v", run_id="source", task="diagnostic reach", frames=frames,
             quality=N(review_reasons=[], inference_mode="fixture"))


def test_retiming_gap_gate_and_real_physics(panda, tmp_path):
    from packages.robot.retarget import retarget
    from packages.robot.simulation import replay
    from packages.geometry.math3d import matrix_quaternion
    p, r = panda.fk(panda.home)
    config = RobotizationConfig(hand_id="h", object_id="o", shot_id="s", end_s=.6,
        calibration=Calibration(mode="measured", evidence="synthetic known coordinates", residual_m=0),
        tcp_quaternion_xyzw=matrix_quaternion(r), initial_gripper="open")
    trajectory = retarget(make_itr(panda), config, panda, "test")
    assert trajectory.frames and all(f.valid for f in trajectory.frames)
    assert all(np.max(np.abs(f.velocity_rad_s)/panda.velocity) <= 1.001 for f in trajectory.frames)
    assert all(np.max(np.abs(f.acceleration_rad_s2)/panda.acceleration) <= 1.001 for f in trajectory.frames)
    report = replay(trajectory, "data/robots/franka_emika_panda", tmp_path, render=False)
    assert report["physics_stepped"] and len(report["states"]) == len(trajectory.frames)
    assert report["task_success"] is None
    assert classify(trajectory, report, {"roundtrip_passed": True}).classification != "Gold"
    config.max_gap_s = .1
    from packages.common.utils import DomainError
    with pytest.raises(DomainError, match="geometry gap"):
        retarget(make_itr(panda), config, panda, "broken")


def test_identity_change_cannot_be_interpolated(panda):
    from packages.robot.retarget import retarget
    from packages.common.utils import DomainError
    itr = make_itr(panda)
    itr.frames[2].hands[0].track_id = "new-unverified-track"
    cfg = RobotizationConfig(hand_id="h", object_id="o", shot_id="s", end_s=.7)
    with pytest.raises(DomainError, match="identity change"):
        retarget(itr, cfg, panda, "bad")

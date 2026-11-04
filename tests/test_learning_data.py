from pathlib import Path
from types import SimpleNamespace as N
import numpy as np
import pytest
from packages.schemas.robotization import TaskScene
from packages.robot.tasks import TaskEvaluator
from packages.robot.rl import export_transitions


def test_pick_place_requires_real_lift_support_release_and_persistence():
    scene = TaskScene(task='pick_place',evidence='unit-test scene',goal_position_m=[.6,0,.035])
    task = TaskEvaluator(scene)
    # Object initially placed at goal is not a demonstrated pick/place.
    assert not task.evaluate([.6,0,.2],[.6,0,.035],.08,1)['success']
    task.evaluate([.5,0,.2],[.5,0,.15],.04,.1)
    assert not task.evaluate([.6,0,.2],[.6,0,.035],.01,1)['success']
    assert not task.evaluate([.6,0,.2],[.6,0,.035],.08,.1)['success']
    assert task.evaluate([.6,0,.2],[.6,0,.035],.08,.1)['success']
    assert not task.evaluate([.6,0,.2],[.6,0,.035],.08,.1,['COLLISION'])['success']


def test_rl_recording_end_is_truncation_and_final_unobserved_action_is_excluded(tmp_path):
    scene = TaskScene(task='reach',evidence='test',goal_position_m=[.4,0,.4])
    frames = [N(valid=True,gripper_width_m=.08,joints_rad=[i*.01]*7,execution_time_s=i*.1,source_time_s=i*.1) for i in range(3)]
    trajectory = N(frames=frames,config=N(task_scene=scene,control_hz=10),source_run_id='source',run_id='run')
    states = [dict(joints_rad=[0.]*7,gripper_width_m=.08,joint_velocity_rad_s=[0.]*7,tcp_position_m=[0.]*3,
        proxy_object_position_m=[0.]*3,execution_time_s=i*.1,sim_time_s=i*.1,task={'reward':-.1,'success':False}) for i in range(3)]
    sim = dict(physics_stepped=True,states=states)
    result = export_transitions(trajectory,sim,N(accepted_training_subset=False),tmp_path)
    assert result['transitions']==2 and result['roundtrip_passed']
    import pyarrow.parquet as pq
    rows = pq.read_table(tmp_path/'transitions.parquet').to_pylist()
    assert rows[0]['action'][0] == pytest.approx(.01)  # upcoming endpoint, not preceding target
    assert rows[-1]['truncated'] and not rows[-1]['terminated'] and rows[-1]['discount']==1
    states[1]['task']['success'] = True
    result = export_transitions(trajectory,sim,N(accepted_training_subset=False),tmp_path)
    assert result['transitions']==1
    frames[1].gripper_width_m=None
    with pytest.raises(ValueError): export_transitions(trajectory,sim,N(accepted_training_subset=False),tmp_path)


def test_bundle_rejects_path_escape(tmp_path):
    import zipfile
    from scripts.verify_learning_bundle import verify
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z: z.writestr('../escaped','bad')
    with pytest.raises(ValueError,match='escapes'): verify(archive,tmp_path/'output')

import numpy as np
import pytest
from packages.robot.calibration import fit_calibration


def test_measured_calibration_recovers_direction_scale_and_rejects_degenerate():
    points=np.random.default_rng(8).normal(size=(12,3))
    c=fit_calibration(points,points*.25+[.2,-.1,.7],'Measured fiducial correspondences')
    assert c.scale_m_per_unit==pytest.approx(.25)
    assert np.allclose(np.array(c.base_from_world)[:3,3],[.2,-.1,.7])
    assert c.correspondence_count==12 and c.residual_m<1e-10
    with pytest.raises(ValueError):fit_calibration(np.zeros((4,3)),np.zeros((4,3)),'Invalid')
    with pytest.raises(ValueError):fit_calibration(points,np.random.default_rng(9).normal(size=(12,3)),'Inconsistent',.001)


def test_fr3_composed_asset_fk_ik_and_model_guard():
    from pathlib import Path
    pytest.importorskip('mujoco')
    if not Path('data/robots/franka_fr3/asset_manifest.json').exists():pytest.skip('FR3 assets not installed')
    from packages.robot.panda import Panda
    from packages.schemas.robotization import RobotizationConfig
    from packages.robot.retarget import retarget
    from packages.common.utils import DomainError
    robot=Panda('data/robots/franka_fr3');p,r=robot.fk(robot.home)
    q,pe,re,collisions=robot.ik(p,r,robot.home)
    assert pe<1e-6 and re<1e-6 and not collisions
    assert robot.spec['joint_order'][0]=='fr3_joint1'
    # Gymnasium lives in the isolated learning runtime, not the API interpreter.
    if Path('/opt/lerobot/bin/python').is_file():
        import subprocess
        subprocess.run(['/opt/lerobot/bin/python','-c',
            "import numpy as np; from packages.robot.environment import PandaTaskEnv; "
            "env=PandaTaskEnv('data/robots/franka_fr3',{'task':'reach','goal_position_m':[.4,0,.4],'evidence':'Synthetic FR3 diagnostic'}); "
            "o,_=env.reset(seed=11); assert o.shape==(25,) and np.isfinite(o).all(); env.step(env.last_command.astype(np.float32)); env.close()"],check=True,timeout=60)
    with pytest.raises(DomainError,match='does not match'):
        retarget(None,RobotizationConfig(hand_id='h',object_id='o',shot_id='s'),robot,'bad')


def test_calibration_api_and_catalog_bounds(database):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        points=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]]
        response=client.post('/v1/calibration/fit',json={'world_points':points,
            'base_points_m':(np.array(points)*.2+[.1,.2,.3]).tolist(),'evidence':'Measured test correspondences'})
        assert response.status_code==200,response.text
        assert response.json()['scale_m_per_unit']==pytest.approx(.2)
        assert client.post('/v1/calibration/fit',json={'world_points':[[0,0,0]]*3,
            'base_points_m':[[0,0,0]]*3,'evidence':'degenerate'}).status_code==422
        assert client.get('/v1/datasets?limit=101').status_code==422
        assert client.get('/v1/datasets?quality=Gold').json()['datasets']==[]
        assert client.get('/v1/videos/missing/robotize/proposal?source_job_id=missing').status_code==404
        inventory=client.get('/v1/runtime/configuration')
        assert inventory.status_code==200 and 'meta_key_configured' in inventory.json()
        assert 'model_api_key' not in inventory.json()


def test_proposals_never_bridge_identity_or_time_gaps():
    from types import SimpleNamespace as N
    from packages.robot.proposal import suggest
    def frame(t,track):
        pose=N(position_xyz=[t,0,0])
        return N(timestamp=t,shot_id='s',world_frame='w',hands=[N(entity_id='h',track_id=track,pose=pose)],
            objects=[N(entity_id='o',track_id='o',pose=pose)],contacts=[])
    itr=N(entities=[N(entity_id='h',role='actor'),N(entity_id='o',role='manipulated_object')],
        frames=[frame(0,'a'),frame(.2,'b'),frame(.8,'b')])
    assert not suggest(itr)['available']
    itr.frames.append(frame(1,'b'))
    result=suggest(itr)
    assert result['available'] and result['requires_review']
    assert result['config']['start_s']==.8 and result['config']['end_s']==1
    assert result['config']['task_scene']['task']=='reach'


def test_requested_export_failure_blocks_training_eligibility():
    from types import SimpleNamespace as N
    from packages.robot.quality import classify
    trajectory=N(inference_mode='live',frames=[N(valid=True)],review_reasons=[],config=N(calibration=N(mode='measured')))
    simulation={'physics_stepped':True,'passed':True,'task_scene_validated':True,'task_success':True}
    report=classify(trajectory,simulation,{'roundtrip_passed':True,'requested_formats_passed':False})
    assert report.classification=='Reject' and not report.accepted_training_subset
    assert 'requested_exports' in report.reasons

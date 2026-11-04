from packages.robot.coverage import coverage
from packages.schemas.robotization import RobotizationConfig
from packages.schemas.reconstruction import ReconstructionConfig


def frame(t,track='hand'):
    return {'timestamp':t,'shot_id':'s','world_frame':'w','hands':[{'entity_id':'h','track_id':track,'pose':{}}],
        'objects':[{'entity_id':'o','track_id':'object','pose':{}}]}


def test_full_interval_rejects_short_excerpt_and_internal_gaps():
    cfg=RobotizationConfig(hand_id='h',object_id='o',shot_id='s',end_s=22.87,require_full_interval=True)
    report=coverage([frame(17),frame(17.2)],cfg)
    assert not report['ready_for_ik_attempt'] and len(report['reasons'])==2
    # Worker guard applies even when a client bypasses the HTTP preflight.
    from types import SimpleNamespace as N
    from packages.robot.retarget import retarget
    from packages.common.utils import DomainError
    import pytest
    itr=N(frames=[N(model_dump=lambda **_:frame(17)),N(model_dump=lambda **_:frame(17.2))])
    with pytest.raises(DomainError,match='Missing paired geometry'):
        retarget(itr,cfg,N(spec={'robot_id':'panda'}),'bad')
    report=coverage([frame(0),frame(.2),frame(22.8)],cfg)
    assert report['unsupported_gaps_s']==[[.2,22.8]]
    assert not report['ready_for_ik_attempt']


def test_full_interval_coverage_has_boundary_tolerance_but_never_joins_identities():
    cfg=RobotizationConfig(hand_id='h',object_id='o',shot_id='s',end_s=1,require_full_interval=True)
    assert coverage([frame(i/5) for i in range(5)],cfg)['ready_for_ik_attempt']
    assert not coverage([frame(i/5,'other' if i==2 else 'hand') for i in range(5)],cfg)['ready_for_ik_attempt']
    assert ReconstructionConfig(windowed=True,memory_mode='low_vram',max_frames_per_shot=117,max_total_frames=117)

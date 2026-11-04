"""Advisory compilation configuration from observed continuous ITR segments."""
from collections import defaultdict
from packages.robot.retarget import construct_targets,gripper_transition
from packages.schemas.robotization import RobotizationConfig,TaskScene


def suggest(itr,robot_id='panda',hand_id=None,object_id=None):
    actors=[e.entity_id for e in itr.entities if e.role=='actor' and (not hand_id or e.entity_id==hand_id)]
    objects=[e.entity_id for e in itr.entities if e.role!='actor' and (not object_id or e.entity_id==object_id)]
    roles={e.entity_id:e.role for e in itr.entities}
    groups=defaultdict(list)
    for frame in itr.frames:
        for h in frame.hands:
            if h.entity_id not in actors or h.pose is None:continue
            for o in frame.objects:
                if o.entity_id not in objects or o.pose is None:continue
                groups[(h.entity_id,o.entity_id,frame.shot_id,frame.world_frame,h.track_id,o.track_id)].append((frame,h,o))
    candidates=[]
    for key,values in groups.items():
        chunks=[]
        for item in sorted(values,key=lambda v:v[0].timestamp):
            if not chunks or item[0].timestamp-chunks[-1][-1][0].timestamp>.3+1e-9:chunks.append([])
            chunks[-1].append(item)
        for chunk in chunks:
            if len(chunk)<2:continue
            known=0;contact=0
            for frame,_,_ in chunk:
                evidence=[c for c in frame.contacts if c.hand_id==key[0] and c.object_id==key[1]]
                state=gripper_transition('unknown',evidence)
                known+=state!='unknown';contact+=state in ('closed','hold')
            score=100*known/len(chunk)+20*contact/len(chunk)+10*(roles[key[1]]=='manipulated_object')+min(len(chunk),20)
            candidates.append((score,key,chunk,known))
    if not candidates:return {'available':False,'reasons':['No continuous interval contains at least two paired associated hand/object samples. Review identities or reconstruct denser geometry.']}
    _,key,chunk,known=max(candidates,key=lambda c:c[0])
    cfg=RobotizationConfig(robot_id=robot_id,hand_id=key[0],object_id=key[1],shot_id=key[2],
        start_s=chunk[0][0].timestamp,end_s=chunk[-1][0].timestamp,workspace_extent_m=.02,
        execution_speed_scale=.25,final_hold_s=.5)
    targets,_=construct_targets(chunk,cfg)
    cfg.task_scene=TaskScene(task='reach',goal_position_m=targets[-1].tolist(),horizon_s=15,
        evidence='Advisory endpoint adaptation of observed motion; source manipulation and grasp are not validated')
    return {'available':True,'config':cfg.model_dump(mode='json'),'paired_samples':len(chunk),'known_gripper_samples':known,
        'reasons':['Suggestion uses estimated source geometry and a configured tool orientation.','Endpoint reach is an adapted task, not validation of the original manipulation.'],
        'requires_review':True,'scope':'single-arm endpoint adaptation'}

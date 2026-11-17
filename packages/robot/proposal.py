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


def suggest_skill(itr,robot_id='panda',hand_id=None,object_id=None,plan=None):
    """Best supported articulated skill over every observed hand/object pair and shot."""
    from packages.common.utils import DomainError
    from packages.robot.skill import extract_skill
    actors=[e.entity_id for e in itr.entities if e.role=='actor' and (not hand_id or e.entity_id==hand_id)]
    objects=[e.entity_id for e in itr.entities if e.role!='actor' and (not object_id or e.entity_id==object_id)]
    found=[];failures=set()
    for shot in sorted({f.shot_id for f in itr.frames}):
        times=[f.timestamp for f in itr.frames if f.shot_id==shot]
        for hand in actors:
            for thing in objects:
                cfg=RobotizationConfig(robot_id=robot_id,mode='skill',hand_id=hand,object_id=thing,shot_id=shot,
                    start_s=min(times),end_s=max(max(times),min(times)+1e-3),initial_gripper='open')
                try:skill=extract_skill(itr,cfg,plan)
                except DomainError as exc:failures.add(exc.message);continue
                # A measured motion outranks a resting hand whose action is only named by the plan.
                if skill.template!='none':found.append(((skill.kind!='static',skill.confidence),cfg,skill))
                else:failures.add(f'{hand}/{thing} in {shot}: motion looks {skill.kind}')
    if not found:return {'available':False,'reasons':sorted(failures) or ['No hand/object pair has enough pose samples to infer a skill.']}
    _,cfg,skill=max(found,key=lambda c:c[0])
    return {'available':True,'config':cfg.model_dump(mode='json'),'skill':skill.model_dump(mode='json'),
        'paired_samples':skill.samples,'known_gripper_samples':skill.contact_samples,
        'reasons':[f'Inferred a {skill.kind} joint ({skill.template}); direction {skill.direction}. {skill.direction_evidence}.',
            'The robot replays the process on a generated stand-in object; the source object is not reconstructed.',*skill.review_reasons],
        'requires_review':True,'scope':'single-arm articulated skill replication'}

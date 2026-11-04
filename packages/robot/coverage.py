"""Observed paired-pose coverage. A broad requested interval is not evidence."""
def coverage(frames,cfg):
    pairs=[]
    for f in sorted(frames,key=lambda f:f['timestamp']):
        if f['shot_id']!=cfg.shot_id or not cfg.start_s<=f['timestamp']<=cfg.end_s:continue
        hands=[p for p in f['hands'] if p['entity_id']==cfg.hand_id and p['pose'] is not None]
        objects=[p for p in f['objects'] if p['entity_id']==cfg.object_id and p['pose'] is not None]
        if len(hands)==len(objects)==1:pairs.append((f,hands[0],objects[0]))
    reasons=[]
    if len(pairs)<2:reasons.append('Need at least two simultaneous associated hand/object poses in the selected interval')
    if cfg.require_full_interval:
        if not pairs or pairs[0][0]['timestamp']-cfg.start_s>cfg.boundary_tolerance_s+1e-9:
            reasons.append('Missing paired geometry at the requested interval start')
        if not pairs or cfg.end_s-pairs[-1][0]['timestamp']>cfg.boundary_tolerance_s+1e-9:
            reasons.append('Missing paired geometry at the requested interval end')
    gaps=[]
    for a,b in zip(pairs,pairs[1:]):
        if b[0]['timestamp']-a[0]['timestamp']>cfg.max_gap_s+1e-9:
            gaps.append([a[0]['timestamp'],b[0]['timestamp']]);reasons.append('Unsupported geometry gap')
        if a[0]['world_frame']!=b[0]['world_frame']:reasons.append('World frame changes')
        if a[1]['track_id']!=b[1]['track_id'] or a[2]['track_id']!=b[2]['track_id']:reasons.append('Track identity changes')
    return {'ready_for_ik_attempt':not reasons,'paired_samples':len(pairs),'sample_times_s':[p[0]['timestamp'] for p in pairs],
        'requested_interval_s':[cfg.start_s,cfg.end_s],'observed_interval_s':[pairs[0][0]['timestamp'],pairs[-1][0]['timestamp']] if pairs else None,
        'unsupported_gaps_s':gaps,'reasons':sorted(set(reasons)),
        'meaning':'Paired geometry continuity only; does not validate full semantic action, grasp, orientation or dynamics'}

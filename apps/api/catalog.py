"""Bounded dataset catalog; signed artifact links retain immutable run lineage."""
import json
from collections import defaultdict
from typing import Literal
from fastapi import APIRouter,Query
from sqlalchemy import select
from apps.api.db import Artifact,Job,Video,transaction
from packages.common.config import settings
from packages.common.storage import Storage

router=APIRouter()


@router.get('/v1/datasets')
def datasets(quality:Literal['Gold','Silver','Reject']|None=None,limit:int=Query(25,ge=1,le=100)):
    with transaction() as session:
        rows=session.execute(select(Job,Video.filename).join(Video,Job.video_id==Video.id)
            .where(Job.status.in_(['COMPLETED','NEEDS_REVIEW']),Job.config['pipeline'].as_string()=='robotization')
            .order_by(Job.created_at.desc()).limit(limit)).all()
        jobs={job.id:(job,filename) for job,filename in rows}
        artifacts=session.scalars(select(Artifact).where(Artifact.job_id.in_(list(jobs)),
            Artifact.name.in_(['quality_report.json','learning_bundle.zip','rl/rl_report.json','rlds/rlds_report.json']))).all() if jobs else []
    grouped=defaultdict(dict)
    for artifact in artifacts:grouped[artifact.job_id][artifact.name]=artifact
    store=Storage();items=[]
    for job,filename in rows:
        refs=grouped[job.id]
        if 'quality_report.json' not in refs or 'learning_bundle.zip' not in refs:continue
        report=json.loads(store.read(refs['quality_report.json'].manifest['uri']))
        if quality and report['classification']!=quality:continue
        learning=json.loads(store.read(refs['rl/rl_report.json'].manifest['uri'])) if 'rl/rl_report.json' in refs else {}
        items.append({'video_id':job.video_id,'filename':filename,'run_id':job.run_id,'job_id':job.id,
            'quality':report['classification'],'accepted_training_subset':report['accepted_training_subset'],
            'reasons':report['reasons'],'robot':job.config['robotization']['config'].get('robot_id','panda'),
            'task':learning.get('task',{}).get('task'),'transitions':learning.get('transitions',0),
            'bundle_url':store.url(refs['learning_bundle.zip'].manifest['uri']),
            'bundle_sha256':refs['learning_bundle.zip'].manifest['sha256'],
            'rlds_available':bool(json.loads(store.read(refs['rlds/rlds_report.json'].manifest['uri'])).get('roundtrip_passed')) if 'rlds/rlds_report.json' in refs else False,'inference_mode':job.mode})
    return {'datasets':items,'scan_limit':limit,'quality_filter':quality}


@router.get('/v1/runtime/configuration')
def configuration():
    from pathlib import Path
    cfg=settings()
    return {'mode':cfg.inference_mode,'meta_key_configured':bool(cfg.model_api_key),
        'models':{'semantics':cfg.muse_model,'tracking':cfg.sam_model},
        'robots':{key:{'asset_manifest_available':(Path(path)/'asset_manifest.json').is_file()} for key,path in [('panda',cfg.robot_assets),('fr3',cfg.fr3_assets)]},
        'geometry_configured':bool(cfg.geometry_python and cfg.vggt_checkpoint),
        'body_configured':bool(cfg.sam3d_body_checkpoint and cfg.sam3d_mhr_path),
        'rlds_configured':bool(cfg.rlds_python),'note':'Configuration inventory only; worker execution is verified separately. No inference or credential values are returned.'}

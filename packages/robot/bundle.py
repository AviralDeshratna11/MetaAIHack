"""Portable learning artifacts with checksums and explicit external asset requirements."""
import json
import zipfile
from pathlib import Path
from packages.common.utils import file_hash


def build_bundle(output, trajectory, quality):
    output = Path(output)
    files = [p for p in sorted(output.rglob('*')) if p.is_file() and
        (p.relative_to(output).parts[0] in ('export','rl','rlds') or p.name in
        ('robot_trajectory.json','quality_report.json','simulation_report.json','simulation_replay.mp4','export_report.json','source_provenance.json','skill_model.json','replication_report.json')) and
        not p.name.endswith('.log') and p.name != 'export_request.json']
    manifest = {'format':'video2robot-learning-bundle-v1','source_run_id':trajectory.source_run_id,
        'run_id':trajectory.run_id,'source_task':trajectory.task,'simulation_task':trajectory.config.task_scene.model_dump(mode='json') if trajectory.config.task_scene else None,
        'robot':trajectory.robot,'accepted_training_subset':quality.accepted_training_subset,
        'quality':quality.classification,'source_review_reasons':trajectory.review_reasons,
        'asset_requirement':f"Install pinned {trajectory.robot.get('robot_id','panda')} assets using python -m scripts.robot_assets --robot {trajectory.robot.get('robot_id','panda')}; geometry checkpoints are not required for training this compiled bundle",
        'files':{p.relative_to(output).as_posix():file_hash(p) for p in files}}
    path = output/'learning_manifest.json';path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(output/'learning_bundle.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in [*files,path]: archive.write(p,p.relative_to(output).as_posix())
    return manifest

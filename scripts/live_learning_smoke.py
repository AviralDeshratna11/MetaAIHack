"""Queue video-derived robotization and verify every published artifact checksum.

Success here denotes adapted simulation/export execution, not full source-task
acceptance. This entry point never submits upstream hosted inference.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-report',default='eval/reports/pouring-repair.json')
    parser.add_argument('--robot-config',default='configs/pouring-endpoint-adaptation.json')
    parser.add_argument('--key',default='reviewed-source-learning-v3')
    parser.add_argument('--report',default='eval/reports/live-learning.json')
    args=parser.parse_args()
    source=json.loads(Path(args.source_report).read_text());cfg=json.loads(Path(args.robot_config).read_text())
    c=httpx.Client(base_url='http://localhost:58000',timeout=240)
    def call(method,path,**kwargs):
        r=c.request(method,path,**kwargs);r.raise_for_status();return r.json()
    video=source['video_id'];base='/v1/videos/'+video
    body={'source_job_id':source['reconstruction']['job_id'],'idempotency_key':args.key,'allow_review_source':True,'config':cfg}
    preflight=call('POST',base+'/robotize/check',json=body)
    if not preflight['ready_for_ik_attempt']:raise ValueError(json.dumps(preflight))
    job=call('POST',base+'/robotize',json=body)
    started=time.monotonic()
    while time.monotonic()-started<1800:
        detail=call('GET','/v1/jobs/'+job['job_id'])
        if detail['status'] in ('COMPLETED','NEEDS_REVIEW','FAILED','CANCELLED'):break
        time.sleep(2)
    if detail['status'] not in ('COMPLETED','NEEDS_REVIEW'):raise RuntimeError(json.dumps(detail.get('error')))
    suffix='?run_id='+job['run_id']
    artifacts=call('GET',base+'/artifacts'+suffix)['artifacts']
    hashes={}
    for a in artifacts:
        r=c.get(a['url']);r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=a['sha256']:raise ValueError('Artifact hash mismatch: '+a['name'])
        hashes[a['name']]=a['sha256']
    quality=call('GET',base+'/robot-quality'+suffix)
    simulation=call('GET',base+'/simulation-report'+suffix)
    learning=call('GET',base+'/learning-report'+suffix)
    passed=simulation['passed'] and quality['checks']['trajectory_valid'] and quality['checks']['export_roundtrip'] and learning.get('roundtrip_passed')
    report={'status':'adapted_simulation_learning_passed' if passed else 'failed','job_id':job['job_id'],
        'run_id':job['run_id'],'video_id':video,'source_job_id':body['source_job_id'],
        'elapsed_s':round(time.monotonic()-started,3),'preflight':preflight,'artifact_hashes_verified':len(hashes),
        'artifact_hashes':hashes,'quality':quality,'learning':learning,
        'simulation':{k:v for k,v in simulation.items() if k!='states'},
        'hosted_inference_requests':0,'source_task_accepted':False,
        'task_scope':'Endpoint reach adaptation of a short stirring-motion interval, not validated stirring or pouring'}
    Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('artifact_hashes','simulation','learning')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()

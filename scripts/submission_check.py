"""Read-only submission inventory: no inference calls or automatic promotion of reports."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
import httpx


def check(api,report):
    head=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    dirty=bool(subprocess.run(['git','status','--porcelain'],capture_output=True,text=True).stdout.strip())
    sources={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for root in ('packages','workers','apps/api','apps/web/src','scripts')
        for p in sorted(Path(root).rglob('*')) if p.is_file() and p.suffix in ('.py','.tsx','.ts')}
    source_hash=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()
    checks={};evidence={}
    for name,path in {'phase1':'eval/reports/live-smoke.json','geometry':'eval/reports/live-phase2-geometry.json',
        'learning':'eval/reports/robot-learning-acceptance.json','fr3':'eval/reports/fr3-software-smoke.json',
        'rlds':'eval/reports/rlds-software-check.json'}.items():
        p=Path(path)
        evidence[name]={'available':p.is_file(),'path':path,'scope':'Recorded evidence; not fresh inference'}
        if p.is_file():evidence[name]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    with httpx.Client(base_url=api,timeout=30) as client:
        for name,path in {'health':'/health/live','configuration':'/v1/runtime/configuration','datasets':'/v1/datasets'}.items():
            try:
                response=client.get(path);response.raise_for_status();data=response.json();checks[name]=True
                if name=='configuration':evidence['runtime']=data
                if name=='datasets':evidence['dataset_count']=len(data['datasets'])
            except (httpx.HTTPError,ValueError,KeyError):checks[name]=False
        try:
            spec=client.get('/openapi.json');spec.raise_for_status();paths=spec.json()['paths']
            required=['/v1/videos/{video_id}/robotize','/v1/videos/{video_id}/robotize/proposal',
                '/v1/calibration/fit','/v1/datasets','/v1/runtime/configuration']
            checks['submission_routes']=all(p in paths for p in required)
        except (httpx.HTTPError,ValueError,KeyError):checks['submission_routes']=False
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'git_head':head,'working_tree_dirty':dirty,'source_hash':source_hash,'checks':checks,'evidence':evidence,
        'passed':all(checks.values()),'scope':'Service and evidence inventory only; tests/build must run separately',
        'fresh_model_calls':0,'full_source_manipulation_validated':False,
        'extensions_not_accepted':['SAM 3D Objects','DINO re-ID','RLBench','bimanual','dexterous retargeting','physical robot deployment']}
    Path(report).parent.mkdir(parents=True,exist_ok=True);Path(report).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':checks,'report':report}));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--api',default='http://localhost:58000');parser.add_argument('--report',default='eval/reports/submission-check.json')
    args=parser.parse_args();raise SystemExit(0 if check(args.api,args.report)['passed'] else 1)

"""Reproduce the assistant-reviewed associations from the supplied pouring frame.

This source-specific acceptance helper reuses stored masks and never requests
hosted inference. It is not an autonomous identity benchmark or generic repair.
"""
import argparse
import json
import time
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reconstruct',action='store_true')
    parser.add_argument('--report',default='eval/reports/pouring-repair.json')
    parser.add_argument('--video',default='vid_689eeec47c9640bcb92d89fcb17406a4')
    parser.add_argument('--source-job',default='job_922277ea40db42038ebf7a91ea08eae1')
    parser.add_argument('--entity-map',help='JSON object mapping visually reviewed semantic entity IDs to provider candidate IDs')
    args=parser.parse_args()
    c=httpx.Client(base_url='http://localhost:58000',timeout=240)
    source=args.source_job
    video=args.video
    target=Path(args.report)
    results={'source_job_id':source,'video_id':video,'reviewer':'assistant','hosted_inference_requests':0,'corrections':[]}
    def call(method,path,**kwargs):
        response=c.request(method,path,**kwargs);response.raise_for_status();return response.json()
    def wait(job):
        deadline=time.monotonic()+2400
        while time.monotonic()<deadline:
            detail=call('GET','/v1/jobs/'+job['job_id'])
            if detail['status'] in ('COMPLETED','NEEDS_REVIEW'): return detail
            if detail['status'] in ('FAILED','CANCELLED'): raise RuntimeError(json.dumps(detail.get('error')))
            time.sleep(3)
        raise TimeoutError('Job did not finish within explicit timeout')
    mapping=json.loads(args.entity_map) if args.entity_map else {'HAND_A':'0','HAND_B':'1','GLASS':'0','BOWL':'0','SPOON':'0'}
    for entity,candidate in mapping.items():
        job=call('POST',f'/v1/videos/{video}/corrections',json={'source_job_id':source,'entity_id':entity,
            'shot_id':'shot_000','frame_index':250,'kind':'association','provider_track_id':candidate,
            'reviewed_by':'assistant','evidence':'Reviewed supplied frame near 16.7s: foreground supporting hand, background spoon hand, glass, bowl and spoon; validated against stored candidate boxes'})
        results['corrections'].append(job);target.write_text(json.dumps(results,indent=2),encoding='utf-8')
        results['corrections'][-1]=wait(job);source=job['job_id'];print(entity+' association completed',flush=True)
    if args.reconstruct:
        job=call('POST',f'/v1/videos/{video}/reconstruct',json={'source_job_id':source,'idempotency_key':'reviewed-dense-stir-v1',
            'allow_review_source':True,'config':{'backend':'vggt','body_backend':'sam3d','memory_mode':'low_vram',
            'image_size':224,'windowed':True,'start_s':16.4,'end_s':17.6,'sample_fps':5,'max_frames_per_shot':16,'max_total_frames':16}})
        results['reconstruction']=job;target.write_text(json.dumps(results,indent=2),encoding='utf-8')
        wait(job)
        suffix='?run_id='+job['run_id']
        results['geometry']=call('GET',f'/v1/videos/{video}/geometry-report'+suffix)
        results['handoff']=call('GET',f'/v1/videos/{video}/phase2-handoff'+suffix)
    target.write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results),flush=True)


if __name__=='__main__':main()

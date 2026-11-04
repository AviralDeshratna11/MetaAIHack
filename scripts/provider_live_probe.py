"""Bounded fresh provider contract probe on a real two-second video excerpt.

This is a provider test, not the app's 10-second-minimum upload acceptance. Raw
responses and the durable request ledger stay under ignored data/.
"""
import json
from pathlib import Path
import cv2
from packages.common.utils import DomainError
from packages.meta_client.live import LiveProvider
from workers.semantic.parser import parse_semantics


class ProbeRecorder:
    mode='live'
    def __init__(self,path):
        self.path=path;self.last_id='';self.cache_hits=0
        self.records=json.loads(path.read_text()) if path.exists() else []
    def lookup(self,key):
        rows=[r for r in self.records if r['request_key']==key]
        if not rows:return None
        row=rows[-1]
        if row['status'] in ('started','unknown'):raise DomainError('E_PROVIDER_OUTCOME_UNKNOWN','Earlier probe outcome requires review')
        if row['status']=='completed':
            self.cache_hits+=1;self.last_id=row.get('request_id','')
            return json.loads(row['raw_output'])
        return None
    def __call__(self,event):
        if event['status']=='started' and sum(r['status']=='started' for r in self.records)>=8:
            raise ValueError('Explicit eight-attempt probe budget exhausted')
        self.records.append(event);self.last_id=event.get('request_id','')
        self.path.write_text(json.dumps(self.records),encoding='utf-8')


def main():
    root=Path('data/provider-probe');root.mkdir(exist_ok=True)
    video=root/'real-stirring-2s.mp4'
    if not video.exists():
        cap=cv2.VideoCapture('data/live-tests/pexels-6901293-preprocessed/video_720p_15fps.mp4')
        cap.set(cv2.CAP_PROP_POS_FRAMES,225)
        writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),15,(1280,720))
        if not writer.isOpened():raise RuntimeError('Probe encoder unavailable')
        for _ in range(30):
            ok,frame=cap.read()
            if not ok:raise RuntimeError('Source frame missing')
            writer.write(frame)
        cap.release();writer.release()
    recorder=ProbeRecorder(root/'ledger.json');provider=LiveProvider()
    plan,_=parse_semantics(provider,video,2.,recorder)
    rows=provider.track(video,'spoon',1280,720,[],recorder)
    calls=[{k:r.get(k) for k in ('model','status','request_id','latency_ms','usage','attempt')} for r in recorder.records if r['status']!='started']
    report={'status':'completed','source':'licensed pouring source, canonical frames 225-254',
        'provider_test_duration_s':2,'calls':calls,'cache_hits':recorder.cache_hits,
        'actual_cost_usd':None,'semantic_primitives':[a.primitive.value for a in plan.actions],
        'semantic_task':plan.task,'tracking_records':len(rows),'tracked_frames':len({r['frame'] for r in rows}),
        'mask_accuracy':'not_evaluated','full_source_acceptance':False}
    Path('eval/reports/fresh-provider-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()

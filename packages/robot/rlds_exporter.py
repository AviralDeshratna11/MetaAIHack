"""Official TFDS nested-episode RLDS export in an isolated TensorFlow runtime."""
import argparse
import hashlib
import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path


def export_isolated(python,input_dir,output):
    if not python:raise ValueError('Configure RLDS_PYTHON to export RLDS')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    process=subprocess.run([python,'-m','packages.robot.rlds_exporter','--input',str(Path(input_dir).resolve()),
        '--output',str(output.resolve())],capture_output=True,timeout=600,
        env={**os.environ,'TF_CPP_MIN_LOG_LEVEL':'2','TF_NUM_INTEROP_THREADS':'1','TF_NUM_INTRAOP_THREADS':'1','CUDA_VISIBLE_DEVICES':'-1'})
    (output/'rlds_stdout.log').write_bytes(process.stdout);(output/'rlds_stderr.log').write_bytes(process.stderr)
    if process.returncode:raise ValueError('RLDS export failed; inspect rlds_stderr.log')
    return json.loads((output/'rlds_report.json').read_text())


def export(input_dir,output):
    import numpy as np
    import pyarrow.parquet as pq
    import tensorflow as tf
    import tensorflow_datasets as tfds
    input_dir,output=Path(input_dir),Path(output)
    report=json.loads((input_dir/'rl_report.json').read_text());path=input_dir/'transitions.parquet'
    if not report.get('roundtrip_passed') or hashlib.sha256(path.read_bytes()).hexdigest()!=report['sha256']:
        raise ValueError('RL transition integrity check failed')
    rows=pq.read_table(path).to_pylist()
    if not rows:raise ValueError('No RL transitions')
    episodes={}
    for row in rows:episodes.setdefault(row['episode_index'],[]).append(row)
    generated=[]
    for index,group in sorted(episodes.items()):
        group=sorted(group,key=lambda r:r['step_index'])
        for a,b in zip(group,group[1:]):
            if b['step_index']!=a['step_index']+1 or not np.allclose(a['next_observation'],b['observation'],atol=1e-6):
                raise ValueError('Discontinuous episode; split it explicitly before RLDS export')
        if not (group[-1]['terminated'] or group[-1]['truncated']):raise ValueError('Episode end missing')
        steps=[]
        for i,row in enumerate(group):
            steps.append({'observation':np.asarray(row['observation'],np.float32),'action':np.asarray(row['action'],np.float32),
                'reward':np.float32(row['reward']),'discount':np.float32(row['discount']),
                'is_first':i==0,'is_last':False,'is_terminal':False,'action_valid':True})
        steps.append({'observation':np.asarray(group[-1]['next_observation'],np.float32),'action':np.zeros(8,np.float32),
            'reward':np.float32(0),'discount':np.float32(0),'is_first':False,'is_last':True,
            'is_terminal':bool(group[-1]['terminated']),'action_valid':False})
        generated.append({'steps':steps,'episode_id':group[0]['run_id']+':'+str(index),
            'source_run_id':group[0]['source_run_id'],'task':json.dumps(report['task'],sort_keys=True),
            'accepted_training_subset':bool(report.get('accepted_training_subset',False))})
    class Video2RobotRlds(tfds.core.GeneratorBasedBuilder):
        VERSION=tfds.core.Version('1.0.0')
        def _info(self):
            step={'observation':tfds.features.Tensor(shape=(21,),dtype=np.float32),'action':tfds.features.Tensor(shape=(8,),dtype=np.float32),
                'reward':tfds.features.Scalar(dtype=np.float32),'discount':tfds.features.Scalar(dtype=np.float32),
                **{key:tfds.features.Scalar(dtype=np.bool_) for key in ('is_first','is_last','is_terminal','action_valid')}}
            return tfds.core.DatasetInfo(builder=self,features=tfds.features.FeaturesDict({'steps':tfds.features.Dataset(step),
                'episode_id':tfds.features.Text(),'source_run_id':tfds.features.Text(),'task':tfds.features.Text(),
                'accepted_training_subset':tfds.features.Scalar(dtype=np.bool_)}),description='Simulated robot transitions with explicit provenance and review eligibility')
        def _split_generators(self,dl_manager):return {'train':self._generate_examples()}
        def _generate_examples(self):
            for episode in generated:yield episode['episode_id'],episode
    output.mkdir(parents=True,exist_ok=True)
    builder=Video2RobotRlds(data_dir=str(output/'dataset'));builder.download_and_prepare()
    reader=tfds.builder_from_directory(str(builder.data_dir));count=0
    for episode in reader.as_dataset(split='train',shuffle_files=False):
        observed=list(episode['steps'].as_numpy_iterator());count+=1
        source=next(e for e in generated if e['episode_id']==episode['episode_id'].numpy().decode())
        for key in ('source_run_id','task'):
            if episode[key].numpy().decode()!=source[key]:raise ValueError('RLDS provenance mismatch: '+key)
        if bool(episode['accepted_training_subset'].numpy())!=source['accepted_training_subset']:
            raise ValueError('RLDS eligibility changed')
        expected=source['steps']
        if len(observed)!=len(expected):raise ValueError('RLDS episode length changed')
        for a,b in zip(observed,expected):
            for key in a:
                if not np.allclose(a[key],b[key],atol=1e-6):raise ValueError('RLDS reader mismatch: '+key)
        if not observed[0]['is_first'] or not observed[-1]['is_last'] or observed[-1]['action_valid']:
            raise ValueError('RLDS episode markers invalid')
    result={'format':'RLDS via official TFDS','roundtrip_passed':True,'episodes':count,'transitions':len(rows),
        'final_observation_included':True,'tensorflow':tf.__version__,'tensorflow_datasets':tfds.__version__,
        'builder_directory':Path(builder.data_dir).relative_to(output).as_posix(),
        'observation_source':'simulated','source_task_validated':False,'accepted_training_subset':report.get('accepted_training_subset',False),
        'source_transitions_sha256':report['sha256'],'protobuf':version('protobuf')}
    (output/'rlds_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(export(args.input,args.output)))

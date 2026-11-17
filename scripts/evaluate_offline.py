"""Reload a saved offline policy and replay it in the matching declared simulator."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from packages.common.utils import file_hash
from packages.robot.environment import PandaTaskEnv
from scripts.train_offline import network, SMOOTHING


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--assets',default='data/robots/franka_emika_panda')
    parser.add_argument('--seed',type=int,default=117)
    parser.add_argument('--video',type=Path)
    args=parser.parse_args()
    report=json.loads((args.data/'rl_report.json').read_text())
    if file_hash(args.data/'transitions.parquet')!=report['sha256']:raise ValueError('Dataset hash mismatch')
    checkpoint=torch.load(args.policy,map_location='cpu',weights_only=True)
    actor=network(checkpoint['observation_dim'],8,True,int(checkpoint.get('hidden_dim',64)));actor.load_state_dict(checkpoint['actor']);actor.eval()
    env=PandaTaskEnv(args.assets,report['task'],control_hz=report['control_hz'],
        initial_joints=report['initial_command_joints_rad'],initial_gripper_width_m=report['initial_gripper_width_m'],
        render_mode='rgb_array' if args.video else None)
    obs,_=env.reset(seed=args.seed);terminated=truncated=False;total=0.;frames=0;writer=None;previous=np.zeros(8,np.float32)
    if args.video:
        import cv2
        args.video.parent.mkdir(parents=True,exist_ok=True)
        writer=cv2.VideoWriter(str(args.video),cv2.VideoWriter_fourcc(*'mp4v'),report['control_hz'],(640,360))
        if not writer.isOpened():raise RuntimeError('Video encoder unavailable')
    try:
        while not (terminated or truncated):
            with torch.no_grad():
                raw=actor(((torch.tensor(obs)-checkpoint['mean'])/checkpoint['std'])[None])[0]
                normalized=(checkpoint['support_low']+checkpoint['support_high'])/2+(checkpoint['support_high']-checkpoint['support_low'])/2*raw
                command=(checkpoint['action_low']+(normalized+1)/2*(checkpoint['action_high']-checkpoint['action_low'])).numpy()
            delta=checkpoint['max_delta'].numpy() if 'max_delta' in checkpoint else np.r_[np.full(7,.0005),.003]
            smoothed=command if frames==0 else SMOOTHING*command+(1-SMOOTHING)*smoothed
            step=np.clip((smoothed if 'max_change' in checkpoint else command)-env.last_command,-delta,delta)
            if 'max_change' in checkpoint:
                change=checkpoint['max_change'].numpy();step=np.clip(step,previous-change,previous+change)
            command=np.clip(env.last_command+step,env.action_space.low,env.action_space.high).astype(np.float32);previous=command-env.last_command
            obs,reward,terminated,truncated,info=env.step(command);total+=reward;frames+=1
            if writer:writer.write(cv2.cvtColor(env.render(),cv2.COLOR_RGB2BGR))
    finally:
        if writer:writer.release()
        env.close()
    if writer:
        # OpenCV's mp4v does not play in browsers; re-encode when FFmpeg is available.
        from packages.robot.video import browser_playable
        browser_playable(args.video)
    result={'policy_sha256':file_hash(args.policy),'seed':args.seed,'steps':frames,'return':total,
        'success':info['success'],'violations':info['violations'],'terminated':terminated,'truncated':truncated,
        'simulation_only':True,'source_task_validated':False}
    print(json.dumps(result))
    if not info['success'] or info['violations']:raise SystemExit(1)


if __name__=='__main__':main()

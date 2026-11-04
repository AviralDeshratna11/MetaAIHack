"""Bounded PPO training on a declared simulation task, with saved evaluation evidence.

This trains an interactive simulator policy; it does not relabel human predictions
as ground truth or claim physical robot readiness.
"""
import argparse
import importlib.metadata
import json
import time
from pathlib import Path
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from gymnasium.utils.env_checker import check_env
from stable_baselines3 import PPO
from packages.robot.environment import PandaTaskEnv
from packages.schemas.robotization import TaskScene
from packages.common.utils import file_hash


class IncrementalControl(gym.ActionWrapper):
    """Normalized bounded increments; explicit adaptation of absolute joint actions."""
    def __init__(self, env):
        super().__init__(env)
        self.action_space = spaces.Box(-1.,1.,shape=(8,),dtype=np.float32)

    def action(self, action):
        action = np.asarray(action,dtype=np.float32)
        if not self.action_space.contains(action): raise ValueError('Invalid incremental action')
        state = np.r_[self.env.data.qpos[self.env.qadr],self.env.data.qpos[self.env.fingers].sum()]
        return np.clip(state+action*np.r_[np.full(7,.015),.003],self.env.action_space.low,self.env.action_space.high).astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task',required=True,type=Path)
    parser.add_argument('--assets',default='data/robots/franka_emika_panda')
    parser.add_argument('--steps',type=int,default=2048)
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--output',type=Path,default=Path('data/training'))
    args = parser.parse_args()
    if not 128 <= args.steps <= 1_000_000: raise ValueError('Use an explicit budget of 128..1000000 steps')
    args.output.mkdir(parents=True,exist_ok=False)
    scene = TaskScene.model_validate_json(args.task.read_text())
    base = PandaTaskEnv(args.assets,scene)
    check_env(base,skip_render_check=True)
    env = IncrementalControl(base)
    started = time.monotonic()
    policy = PPO('MlpPolicy',env,n_steps=128,batch_size=64,n_epochs=4,seed=args.seed,
                 device='cpu',verbose=0,policy_kwargs={'net_arch':[32,32]})
    policy.learn(total_timesteps=args.steps)
    policy.save(args.output/'policy')
    evaluations = []
    for seed in range(args.seed+100,args.seed+105):
        obs, _ = env.reset(seed=seed)
        terminated = truncated = False
        reward_sum = 0.; count = 0
        while not (terminated or truncated):
            action,_ = policy.predict(obs,deterministic=True)
            obs,reward,terminated,truncated,info = env.step(action)
            reward_sum += reward; count += 1
        evaluations.append({'seed':seed,'steps':count,'return':reward_sum,'terminated':terminated,
            'truncated':truncated,'success':info['success'],'violations':info['violations']})
    env.close()
    report = {'status':'training_executed','algorithm':'PPO','requested_steps':args.steps,'actual_steps':policy.num_timesteps,
        'seed':args.seed,'elapsed_s':round(time.monotonic()-started,3),'task':scene.model_dump(mode='json'),
        'control':'normalized increments 0.015 rad and 0.003m per control tick, clipped to absolute bounds',
        'evaluation':evaluations,'success_rate':sum(e['success'] for e in evaluations)/len(evaluations),
        'evaluation_distribution':'identical configured initial state; seeds do not imply task diversity',
        'policy_sha256':file_hash(args.output/'policy.zip'),'observation_source':'simulated',
        'source_video_training':False,'physical_robot_ready':False,
        'versions':{k:importlib.metadata.version(k) for k in ('gymnasium','stable-baselines3','mujoco','torch')}}
    (args.output/'training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__': main()

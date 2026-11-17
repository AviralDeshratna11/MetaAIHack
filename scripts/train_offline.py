"""Train a bounded TD3+BC baseline from exported robot RL transitions.

Algorithm reference: https://github.com/sfujim/TD3_BC. This small baseline uses twin
critics, target smoothing, delayed updates, state normalization and a weighted BC
actor loss. Passing an optimizer smoke does not establish task learning.
"""
import argparse
import copy
import json
import time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import torch
from torch import nn
from torch.nn import functional as F
from packages.common.utils import file_hash
from packages.robot.environment import PandaTaskEnv


SMOOTHING = .3  # weight of the newest policy output in the executed command


def network(inputs, outputs, bounded=False, hidden=64):
    layers = [nn.Linear(inputs,hidden),nn.ReLU(),nn.Linear(hidden,hidden),nn.ReLU(),nn.Linear(hidden,outputs)]
    if bounded: layers.append(nn.Tanh())
    return nn.Sequential(*layers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True,help='Directory containing rl_report.json and transitions.parquet')
    parser.add_argument('--assets',default='data/robots/franka_emika_panda')
    parser.add_argument('--updates',type=int,default=2000)
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--alpha',type=float,default=.1,help='Q contribution relative to normalized behavior loss')
    parser.add_argument('--warmup-updates',type=int,default=1000)
    parser.add_argument('--hidden',type=int,default=64,help='Hidden width; long multi-phase skills need more than short reaches')
    parser.add_argument('--warmup-lr',type=float,default=3e-4)
    parser.add_argument('--state-noise',type=float,default=0.,help='Std of noise added to normalized observations (not time) while cloning; makes a single-demonstration policy tolerate its own drift')
    parser.add_argument('--allow-review',action='store_true',help='Explicitly use diagnostic simulation data; retain all eligibility warnings')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not 10 <= args.updates <= 1_000_000: raise ValueError('Explicit optimizer budget required')
    if not 0 < args.alpha <= 10 or not 0 <= args.warmup_updates <= 100000 or not 16 <= args.hidden <= 1024 or not 0 < args.warmup_lr <= .01 or not 0 <= args.state_noise <= 2:
        raise ValueError('Invalid learning budget/hyperparameter')
    report = json.loads((args.data/'rl_report.json').read_text())
    path = args.data/'transitions.parquet'
    if report.get('roundtrip_passed') is not True or file_hash(path) != report.get('sha256'):
        raise ValueError('Transition provenance/integrity check failed')
    rows = pq.read_table(path).to_pylist()
    if not rows or (not report.get('accepted_training_subset') and not args.allow_review):
        raise ValueError('Reviewed data requires explicit --allow-review; it is not certified human task data')
    if any(r['duration_s'] <= 0 for r in rows): raise ValueError('Invalid transition timing')
    args.output.mkdir(parents=True,exist_ok=False)
    torch.manual_seed(args.seed); np.random.seed(args.seed); torch.set_num_threads(2)
    if 'initial_command_joints_rad' not in report: raise ValueError('Initial controller state missing; regenerate transitions')
    task_config=dict(report['task'])
    if report.get('episode_end')=='trajectory_end':
        task_config['horizon_s']=report['execution_duration_s']
    env = PandaTaskEnv(args.assets,task_config,control_hz=report['control_hz'],initial_joints=report['initial_command_joints_rad'],
        initial_gripper_width_m=report['initial_gripper_width_m'],terminate_on_success=report.get('episode_end','task_success')=='task_success')
    low, high = env.action_space.low, env.action_space.high
    goal = np.asarray(report['task']['goal_position_m'],dtype=np.float32)
    horizon = env.scene.horizon_s
    raw = np.asarray([r['observation']+goal.tolist()+[r['timestamp']/horizon] for r in rows],dtype=np.float32)
    mean, std = raw.mean(0), np.maximum(raw.std(0),.01)
    state = torch.tensor((raw-mean)/std)
    next_state = torch.tensor((np.asarray([r['next_observation']+goal.tolist()+[(r['timestamp']+r['duration_s'])/horizon] for r in rows],np.float32)-mean)/std)
    action = torch.tensor(2*(np.asarray([r['action'] for r in rows],np.float32)-low)/(high-low)-1)
    reward = torch.tensor([r['reward'] for r in rows],dtype=torch.float32)[:,None]
    # Truncation bootstraps; real task termination does not.
    discount = torch.tensor([r['discount'] for r in rows],dtype=torch.float32)[:,None]
    if not all(torch.isfinite(x).all() for x in (state,next_state,action,reward,discount)) or (action.abs()>1.0001).any():
        raise ValueError('Invalid learning features/actions')
    actor = network(25,8,True,args.hidden)
    # The controller adapter may not move a command faster than the demonstration did.
    # A fixed tiny bound suits a short reach and makes a full approach-and-grasp unreachable.
    commands = np.asarray([report['initial_command_joints_rad']+[report['initial_gripper_width_m']]]+[r['action'] for r in rows],np.float32)
    max_delta = np.maximum(np.abs(np.diff(commands,axis=0)).max(0)*1.25,np.r_[np.full(7,.0005),.003]).astype(np.float32)
    # Likewise for how fast that change may itself change: a jittering policy output
    # is an acceleration the demonstration never commanded.
    max_change = np.maximum(np.abs(np.diff(commands,n=2,axis=0)).max(0),np.r_[np.full(7,.0002),.003]).astype(np.float32)
    support_low, support_high = action.min(0).values, action.max(0).values
    def supported(policy, states):
        return (support_low+support_high)/2+(support_high-support_low)/2*policy(states)
    # Start at the demonstration's mean command to avoid arbitrary extreme joint targets.
    nn.init.zeros_(actor[-2].weight)
    nn.init.zeros_(actor[-2].bias)
    q1,q2 = network(33,1,hidden=args.hidden),network(33,1,hidden=args.hidden)
    at,t1,t2 = copy.deepcopy(actor),copy.deepcopy(q1),copy.deepcopy(q2)
    ao = torch.optim.Adam(actor.parameters(),lr=args.warmup_lr)
    qo = torch.optim.Adam(list(q1.parameters())+list(q2.parameters()),lr=3e-4)
    losses = []; started = time.monotonic()
    span = ((support_high-support_low)/2).clamp_min(.0001)
    # One demonstration covers a thin line of states. Without perturbation the clone
    # reacts violently to the small deviations its own rollout creates.
    def perturbed(states):
        noise = torch.randn_like(states)*args.state_noise
        noise[:,-1] = 0  # episode phase is exact at execution time
        return states+noise
    for _ in range(args.warmup_updates):
        pi = supported(actor,perturbed(state))
        loss = ((pi-action)/span).square().mean()
        ao.zero_grad();loss.backward();ao.step()
    at.load_state_dict(actor.state_dict())
    behavior_fit = float(((supported(actor,state)-action)/span).square().mean().detach())
    ao = torch.optim.Adam(actor.parameters(),lr=3e-4)
    for step in range(args.updates):
        idx = torch.randint(len(rows),(min(128,len(rows)),))
        s,a,ns,r,d = state[idx],action[idx],next_state[idx],reward[idx],discount[idx]
        with torch.no_grad():
            na = torch.maximum(support_low,torch.minimum(support_high,supported(at,ns)+(torch.randn_like(a)*.2).clamp(-.5,.5)))
            x = torch.cat((ns,na),1)
            target = r+.99*d*torch.minimum(t1(x),t2(x))
        x = torch.cat((s,a),1)
        qloss = F.mse_loss(q1(x),target)+F.mse_loss(q2(x),target)
        qo.zero_grad(); qloss.backward(); qo.step()
        if step%2 == 0:
            pi = supported(actor,perturbed(s)); q = q1(torch.cat((s,pi),1))
            weight = args.alpha/q.abs().mean().detach().clamp_min(1e-6)
            aloss = -weight*q.mean()+((pi-a)/span).square().mean()
            ao.zero_grad(); aloss.backward(); ao.step()
            with torch.no_grad():
                for current,target_net in ((actor,at),(q1,t1),(q2,t2)):
                    for p,t in zip(current.parameters(),target_net.parameters()): t.mul_(.995).add_(p,alpha=.005)
        if not torch.isfinite(qloss): raise ValueError('Training diverged')
        if step%100 == 0 or step == args.updates-1: losses.append({'update':step,'critic_loss':float(qloss.detach()),'actor_loss':float(aloss.detach())})
    checkpoint = {'actor':actor.state_dict(),'mean':torch.tensor(mean),'std':torch.tensor(std),
        'action_low':torch.tensor(low),'action_high':torch.tensor(high),'support_low':support_low,
        'support_high':support_high,'observation_dim':25,'hidden_dim':args.hidden,'max_delta':torch.tensor(max_delta),'max_change':torch.tensor(max_change)}
    torch.save(checkpoint,args.output/'policy.pt')
    # Reload the saved policy, then test the same configured MDP in real physics.
    saved = torch.load(args.output/'policy.pt',weights_only=True)
    actor.load_state_dict(saved['actor']); actor.eval()
    evaluations=[]
    for seed in range(args.seed+100,args.seed+103):
        obs,_ = env.reset(seed=seed); terminated=truncated=False; total=0.; count=0; step_before=np.zeros(8,np.float32)
        while not (terminated or truncated):
            with torch.no_grad(): normalized = supported(actor,torch.tensor((obs-mean)/std)[None])[0].numpy()
            command = np.clip(low+(normalized+1)/2*(high-low),low,high).astype(np.float32)
            # Declared conservative controller adapter: a learned endpoint cannot
            # jump from the previous command. Actual environment constraints remain
            # checked; no violations are hidden or treated as success.
            # Smooth the raw policy output first: tick-to-tick jitter is not intent.
            smoothed = command if count == 0 else SMOOTHING*command+(1-SMOOTHING)*smoothed
            step_now = np.clip(np.clip(smoothed-env.last_command,-max_delta,max_delta),step_before-max_change,step_before+max_change)
            command = np.clip(env.last_command+step_now,low,high).astype(np.float32); step_before = command-env.last_command
            obs,value,terminated,truncated,info = env.step(command); total+=value; count+=1
        evaluations.append({'seed':seed,'steps':count,'return':total,'success':info['success'],
            'terminated':terminated,'truncated':truncated,'violations':info['violations']})
    env.close()
    result = {'status':'training_executed','algorithm':'TD3+BC','reference':'https://github.com/sfujim/TD3_BC',
        'updates':args.updates,'warmup_updates':args.warmup_updates,'alpha':args.alpha,
        'seed':args.seed,'transitions':len(rows),'dataset_sha256':file_hash(path),
        'policy_sha256':file_hash(args.output/'policy.pt'),'losses':losses,'evaluation':evaluations,
        'success_rate':sum(e['success'] for e in evaluations)/len(evaluations),'elapsed_s':round(time.monotonic()-started,3),
        'evaluation_distribution':'same configured initial state, not evidence of generalization',
        'review_override':args.allow_review,'accepted_training_subset':report['accepted_training_subset'],
        'policy_constraint':'dataset per-joint action support; policy output smoothed (weight 0.3), per-tick command change limited to 1.25x and its rate of change to 1x the fastest in the demonstration','max_command_change_per_tick2':max_change.tolist(),
        'max_command_delta_per_tick':max_delta.tolist(),'behavior_fit_normalized_mse':behavior_fit,'state_noise':args.state_noise,'hidden':args.hidden,
        'source_task_validated':False,'physical_robot_ready':False,'torch':torch.__version__}
    result.update(episode_end=report.get('episode_end','task_success'),evaluation_horizon_s=horizon)
    (args.output/'training_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__': main()

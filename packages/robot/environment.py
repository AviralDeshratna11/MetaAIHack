"""Interactive Gymnasium environment using the same Panda/task scene as replay.

This is an explicitly configured simulation MDP. It is not a recovered real-world
environment and never attaches the object to the gripper.
"""
from pathlib import Path
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import mujoco as mj

from packages.robot.panda import Panda
from packages.robot.scenes import scene_xml, forbidden_contacts
from packages.robot.tasks import TaskEvaluator
from packages.schemas.robotization import TaskScene


class PandaTaskEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 30}

    def __init__(self, assets, scene, control_hz=30, render_mode=None, initial_joints=None, initial_gripper_width_m=.08, terminate_on_success=True):
        super().__init__()
        if render_mode not in (None, "rgb_array"): raise ValueError("Unsupported render mode")
        if not 5 <= control_hz <= 120: raise ValueError("Invalid control frequency")
        self.robot = Panda(Path(assets))
        self.terminate_on_success=terminate_on_success
        self.scene = TaskScene.model_validate(scene) if isinstance(scene,dict) else scene
        self.model = mj.MjModel.from_xml_string(scene_xml(assets,self.scene))
        self.data = mj.MjData(self.model)
        self.qadr = self.model.jnt_qposadr[self.robot.joints]
        self.dadr = self.model.jnt_dofadr[self.robot.joints]
        self.hand = mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_BODY,'hand')
        self.object = mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_BODY,'proxy_object')
        self.fingers = [self.model.jnt_qposadr[mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_JOINT,n)] for n in ('finger_joint1','finger_joint2')]
        self.action_space = spaces.Box(np.r_[self.robot.lower,0].astype(np.float32),np.r_[self.robot.upper,.08].astype(np.float32))
        self.observation_space = spaces.Box(-np.inf,np.inf,shape=(25,),dtype=np.float32)
        self.evaluator = TaskEvaluator(self.scene)
        self.initial_joints = np.asarray(initial_joints if initial_joints is not None else self.robot.home,dtype=float)
        if not np.isfinite(initial_gripper_width_m) or not 0 <= initial_gripper_width_m <= .08:
            raise ValueError('Invalid initial gripper width')
        self.initial_gripper_width_m = initial_gripper_width_m
        if self.initial_joints.shape != (7,) or not np.isfinite(self.initial_joints).all() or np.any(self.initial_joints < self.robot.lower) or np.any(self.initial_joints > self.robot.upper):
            raise ValueError('Invalid initial joints')
        self.control_hz = control_hz
        self.render_mode = render_mode
        self.renderer = None
        self.closed = False
        self.finished = True

    def tcp(self):
        return self.data.xpos[self.hand]+self.data.xmat[self.hand].reshape(3,3)@self.robot.local_tcp

    def observation(self):
        return np.r_[self.data.qpos[self.qadr],self.data.qpos[self.fingers].sum(),self.data.qvel[self.dadr],
            self.tcp(),self.data.xpos[self.object],self.scene.goal_position_m,
            min(float(self.data.time)/self.scene.horizon_s,1.)].astype(np.float32)

    def reset(self, *, seed=None, options=None):
        if self.closed: raise RuntimeError('Environment closed')
        super().reset(seed=seed)
        if options: raise ValueError('Undeclared initial-state overrides are unsupported')
        mj.mj_resetData(self.model,self.data)
        self.data.qpos[self.qadr] = self.initial_joints
        self.data.qpos[self.fingers] = self.initial_gripper_width_m/2
        self.data.ctrl[:7] = self.initial_joints
        self.data.ctrl[7] = self.initial_gripper_width_m/.08*255
        mj.mj_forward(self.model,self.data)
        for _ in range(round(1/self.model.opt.timestep)): mj.mj_step(self.model,self.data)
        self.data.time = 0
        self.steps = 0
        self.last_command = np.r_[self.initial_joints,self.initial_gripper_width_m]
        self.finished = False
        self.evaluator.reset()
        return self.observation(), {'observation_source':'simulated','initial_equilibration_s':1,'source_task_validated':False}

    def step(self, action):
        if self.finished or self.closed: raise RuntimeError('Call reset before stepping a new episode')
        action = np.asarray(action,dtype=np.float32)
        if not self.action_space.contains(action): raise ValueError('Action violates shape, finite values or joint/gripper bounds')
        self.steps += 1
        violations = set()
        while self.data.time < self.steps/self.control_hz-1e-9:
            alpha = np.clip((self.data.time-(self.steps-1)/self.control_hz)*self.control_hz,0,1)
            command = self.last_command*(1-alpha)+action*alpha
            self.data.ctrl[:7],self.data.ctrl[7] = command[:7],command[7]/.08*255
            mj.mj_step(self.model,self.data)
            if not np.isfinite(self.data.qpos).all(): raise RuntimeError('Nonfinite simulation state')
            if np.any(self.data.qpos[self.qadr] < self.robot.lower-.005) or np.any(self.data.qpos[self.qadr] > self.robot.upper+.005): violations.add('JOINT_POSITION')
            if np.any(np.abs(self.data.qvel[self.dadr]) > self.robot.velocity+.01): violations.add('JOINT_VELOCITY')
            if np.any(np.abs(self.data.qacc[self.dadr]) > self.robot.acceleration+.1): violations.add('JOINT_ACCELERATION')
            if forbidden_contacts(self.model,self.data,self.scene.task=='pick_place'): violations.add('COLLISION')
        self.last_command = action.astype(float).copy()
        task = self.evaluator.evaluate(self.tcp(),self.data.xpos[self.object],self.data.qpos[self.fingers].sum(),1/self.control_hz,violations)
        terminated = bool((task['success'] and self.terminate_on_success) or violations)
        truncated = bool(not terminated and self.data.time >= self.scene.horizon_s-1e-9)
        self.finished = terminated or truncated
        return self.observation(),task['reward'],terminated,truncated,{**task,'violations':sorted(violations),'sim_time_s':float(self.data.time)}

    def render(self):
        if self.closed: raise RuntimeError('Environment closed')
        if self.render_mode != 'rgb_array': return None
        if self.renderer is None: self.renderer = mj.Renderer(self.model,height=360,width=640)
        self.renderer.update_scene(self.data,camera='debug')
        return self.renderer.render().copy()

    def close(self):
        if self.renderer is not None: self.renderer.close(); self.renderer = None
        self.closed = True

"""Explicit simulator task semantics. These checks never certify source video."""
import numpy as np


class TaskEvaluator:
    def __init__(self, scene):
        self.scene = scene
        self.reset()

    def reset(self):
        self.lifted = False
        self.held_s = 0.
        self.success = False

    def evaluate(self, tcp, object_position, gripper_width, dt, violations=()):
        scene = self.scene
        tcp, obj, goal = map(np.asarray, (tcp, object_position, scene.goal_position_m))
        distance = float(np.linalg.norm(tcp-goal if scene.task == "reach" else obj-goal))
        self.lifted |= bool(obj[2]-scene.object_position_m[2] >= scene.required_lift_m)
        supported = abs(obj[2]-scene.object_half_size_m[2]-scene.table_top_m) <= .01
        released = gripper_width >= 2*scene.object_half_size_m[0]+.005
        candidate = distance <= scene.goal_tolerance_m and not violations
        if scene.task == "pick_place": candidate &= self.lifted and supported and released
        self.held_s = self.held_s+dt if candidate else 0.
        self.success = self.held_s+1e-9 >= scene.success_hold_s
        # Declared task shaping, not a reward inferred/validated from human footage.
        reward = -distance - (0.1*float(np.linalg.norm(tcp-obj)) if scene.task == "pick_place" and not self.lifted else 0)
        reward += float(self.success)
        reward -= float(bool(violations))
        return {"reward": float(reward), "success": bool(self.success), "distance_m": distance,
                "lift_observed": bool(self.lifted), "supported": bool(supported), "released": bool(released),
                "reward_source": "configured simulator task shaping", "source_task_validated": False}

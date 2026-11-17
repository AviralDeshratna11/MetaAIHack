"""Explicit simulator task semantics. These checks never certify source video."""
import numpy as np


class TaskEvaluator:
    def __init__(self, scene):
        self.scene = scene
        self.reset()

    def reset(self):
        self.lifted = False
        self.reached = False
        self.held_s = 0.
        self.success = False

    def evaluate(self, tcp, object_position, gripper_width, dt, violations=(), joint_value=None):
        scene = self.scene
        if scene.task == "articulated":
            return self.articulated(np.asarray(tcp), np.asarray(object_position), gripper_width, dt, violations, joint_value)
        tcp, obj, goal = map(np.asarray, (tcp, object_position, scene.goal_position_m))
        distance = float(np.linalg.norm(tcp-goal if scene.task == "reach" else obj-goal))
        self.lifted |= bool(obj[2]-scene.object_position_m[2] >= scene.required_lift_m)
        # A goal above the table rests on a generated support of that height.
        supported = abs(obj[2]-scene.object_half_size_m[2]-scene.table_top_m-scene.goal_support_m) <= .012
        released = gripper_width >= 2*min(scene.object_half_size_m[:2])+.005
        candidate = distance <= scene.goal_tolerance_m and not violations
        if scene.task == "pick_place" and scene.hold_at_goal: candidate &= self.lifted and not released
        elif scene.task == "pick_place": candidate &= self.lifted and supported and released
        self.held_s = self.held_s+dt if candidate else 0.
        self.success = self.held_s+1e-9 >= scene.success_hold_s
        # Declared task shaping, not a reward inferred/validated from human footage.
        reward = -distance - (0.1*float(np.linalg.norm(tcp-obj)) if scene.task == "pick_place" and not self.lifted else 0)
        reward += float(self.success)
        reward -= float(bool(violations))
        return {"reward": float(reward), "success": bool(self.success), "distance_m": distance,
                "lift_observed": bool(self.lifted), "supported": bool(supported), "released": bool(released),
                "reward_source": "configured simulator task shaping", "source_task_validated": False}

    def articulated(self, tcp, handle, gripper_width, dt, violations, joint_value):
        """Success: the generated joint holds the demonstrated displacement after release."""
        part = self.scene.articulation
        if joint_value is None:
            raise ValueError("Articulated task evaluation requires the simulated joint value")
        span = abs(part.goal-part.start)
        error = abs(float(joint_value)-part.goal)
        if part.momentary:
            # A button springs back: what counts is that it was pressed, then let go.
            self.reached = getattr(self, "reached", False) or error <= part.tolerance
            error = 0. if self.reached else error
        released = (part.momentary or gripper_width >= .06) and float(np.linalg.norm(tcp-handle)) >= .03
        candidate = error <= part.tolerance and released and not violations
        self.held_s = self.held_s+dt if candidate else 0.
        self.success = self.held_s+1e-9 >= self.scene.success_hold_s
        progress = float(np.clip(1-error/span, 0, 1))
        # Declared shaping: joint progress, then letting go. Not inferred from footage.
        reward = progress-1-.1*float(np.linalg.norm(tcp-handle))*(error > part.tolerance)
        reward += float(self.success)-float(bool(violations))
        return {"reward": float(reward), "success": bool(self.success), "distance_m": float(np.linalg.norm(tcp-handle)),
                "joint_value": float(joint_value), "joint_error": error, "joint_progress": progress,
                "lift_observed": False, "supported": True, "released": bool(released),
                "reward_source": "configured simulator task shaping", "source_task_validated": False}

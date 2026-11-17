"""MuJoCo model-backed FK, constrained sequential IK and collision inspection."""
import json
from pathlib import Path

import numpy as np

from packages.common.utils import DomainError, file_hash, digest


def fingerprint(root):
    root = Path(root)
    manifest_path = root / "asset_manifest.json"
    if not manifest_path.is_file():
        raise DomainError("E_ROBOT_ASSETS", "Run python -m scripts.robot_assets on the robot worker", 503)
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != expected:
            raise DomainError("E_ROBOT_ASSETS", "Robot asset changed or is missing", 503)
    import importlib.metadata
    fr3=manifest.get('robot')=='fr3'
    return {"model": "Franka FR3 with Panda hand (simulation composition)" if fr3 else "Franka Emika Panda", "robot_id":"fr3" if fr3 else "panda", "commit": manifest["commit"], "asset_hash": digest(manifest),
            "mujoco": importlib.metadata.version("mujoco"), "scipy": importlib.metadata.version("scipy"),
            "joint_order": [f"{'fr3_' if fr3 else ''}joint{i}" for i in range(1, 8)], "units": "meters/radians",
            "velocity_limits_rad_s": [1.]*7 if fr3 else [2.175]*4+[2.61]*3, "acceleration_limits_rad_s2": [5.]*7 if fr3 else [15, 7.5, 10, 12.5, 15, 20, 20],
            "limits_source": "Configured 1 rad/s and 5 rad/s2 simulation ceilings; FR3 position bounds and actuator saturation from pinned asset; physical limits not certified" if fr3 else "Franka Panda control parameters; independently constrained trajectory",
            "model_file":"fr3_hand.xml" if fr3 else "panda.xml","base_body":"fr3_link0" if fr3 else "link0",
            "tcp": "hand local z +0.1034m; task orientation configured", "quaternion_order": "xyzw"}


class Panda:
    def __init__(self, root):
        import mujoco
        self.mj = mujoco
        self.root = Path(root)
        self.spec = fingerprint(root)
        self.model = mujoco.MjModel.from_xml_path(str(Path(root) / self.spec['model_file']))
        self.data = mujoco.MjData(self.model)
        self.joints = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in self.spec['joint_order']]
        self.qadr = self.model.jnt_qposadr[self.joints]
        self.dadr = self.model.jnt_dofadr[self.joints]
        self.hand = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "hand")
        if self.hand < 0 or any(j < 0 for j in self.joints):
            raise DomainError("E_ROBOT_MODEL", "Official Panda joint/body naming changed")
        self.lower, self.upper = self.model.jnt_range[self.joints].T
        self.home = np.array([0, -.4, 0, -1.9, 0, 1.5, .7854])
        self.velocity = np.array(self.spec["velocity_limits_rad_s"])
        self.acceleration = np.array(self.spec["acceleration_limits_rad_s2"])
        self.local_tcp = np.array([0, 0, .1034])

    def set_gripper(self, width):
        # Unknown width uses the open envelope for diagnostic collision inspection.
        width = .08 if width is None else width
        for name in ("finger_joint1", "finger_joint2"):
            joint = self.mj.mj_name2id(self.model, self.mj.mjtObj.mjOBJ_JOINT, name)
            self.data.qpos[self.model.jnt_qposadr[joint]] = width/2

    def fk(self, joints):
        self.data.qpos[self.qadr] = joints
        self.mj.mj_forward(self.model, self.data)
        r = self.data.xmat[self.hand].reshape(3, 3).copy()
        return self.data.xpos[self.hand].copy() + r @ self.local_tcp, r

    def collisions(self):
        result = []
        for contact in self.data.contact[:self.data.ncon]:
            if contact.dist >= -1e-5:
                continue
            a, b = (int(self.model.geom_bodyid[g]) for g in (contact.geom1, contact.geom2))
            # Parent-child geometries are the modeled articulated mechanism.
            if a == b or self.model.body_parentid[a] == b or self.model.body_parentid[b] == a:
                continue
            names = [self.mj.mj_id2name(self.model, self.mj.mjtObj.mjOBJ_BODY, v) or str(v) for v in (a, b)]
            result.append("/".join(names))
        return sorted(set(result))

    def ik(self, position, rotation, previous, continuity=True):
        from scipy.optimize import least_squares
        from scipy.spatial.transform import Rotation
        def residual(q):
            p, r = self.fk(q)
            orientation = Rotation.from_matrix(rotation @ r.T).as_rotvec()
            contact_penalty = [.05*len(self.collisions())] if continuity else []
            return np.r_[p-position, .15*orientation, .002*(q-previous) if continuity else [], contact_penalty]
        solution = least_squares(residual, np.clip(previous, self.lower+1e-6, self.upper-1e-6),
                                 bounds=(self.lower+1e-6, self.upper-1e-6), max_nfev=120, diff_step=1e-5)
        p, r = self.fk(solution.x)
        return solution.x, float(np.linalg.norm(p-position)), float(Rotation.from_matrix(rotation @ r.T).magnitude()), self.collisions()

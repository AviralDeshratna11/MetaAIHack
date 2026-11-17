"""Generated articulated stand-ins (lid, door, drawer) and their handle kinematics.

Every template is authored in an object frame ``O`` (z up) and placed in the robot
base by a position and a yaw. The handle is a bar the parallel gripper straddles so
that the finger closing axis is the direction the handle moves: the part is pushed
by a finger surface (form closure) instead of being dragged by pad friction.
These are simulation proxies generated from a skill, never a reconstruction.
"""
import xml.etree.ElementTree as ET

import numpy as np

STANDOFF = .07  # bar-to-face clearance; an open finger must fit behind the bar
LID_OVERHANG = .012
FINGER_REACH = .045  # hand body starts this far behind the TCP along the approach


def axis_rotation(axis, angle):
    axis = np.asarray(axis, float)/np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3)+np.sin(angle)*k+(1-np.cos(angle))*(k @ k)


TEMPLATES = {
    # joint axis, handle at q=0 as a function of radius, approach direction at q=0
    "lid": {"joint": "revolute", "axis": (0, -1, 0), "handle": lambda r: np.array([r, 0, 0]), "approach": (-1, 0, 0)},
    "door": {"joint": "revolute", "axis": (0, 0, -1), "handle": lambda r: np.array([r, -STANDOFF, 0]), "approach": None},
    "drawer": {"joint": "prismatic", "axis": (1, 0, 0), "handle": lambda r: np.zeros(3), "approach": (0, 0, -1)},
    # The grasped bar sits on the axis: it turns in place, so the finger axis is given.
    "knob": {"joint": "revolute", "axis": (0, 0, 1), "handle": lambda r: np.zeros(3), "approach": (0, 0, -1), "finger": (1, 0, 0)},
    # Pressed with closed fingertips along the approach; nothing is grasped.
    "button": {"joint": "prismatic", "axis": (0, 0, -1), "handle": lambda r: np.zeros(3), "approach": (0, 0, -1), "finger": (1, 0, 0)},
}
FINGERTIP = .0095  # closed fingertips end this far beyond the TCP


class Articulation:
    def __init__(self, obj):
        self.obj = obj
        template = TEMPLATES[obj.template]
        self.axis = np.array(template["axis"], float)
        self.handle0 = template["handle"](obj.radius_m)
        self.revolute = template["joint"] == "revolute"
        if template["approach"] is None:
            # Door: slide in radially from the free edge, behind the vertical bar.
            self.approach0 = -self.handle0/np.linalg.norm(self.handle0)
        else:
            self.approach0 = np.array(template["approach"], float)
        tangent = template["finger"] if "finger" in template else np.cross(self.axis, self.handle0) if self.revolute else self.axis
        self.tangent0 = np.asarray(tangent, float)/np.linalg.norm(tangent)
        # A pressing fingertip leads the TCP; hold the TCP back so the tip meets the surface.
        self.standoff = FINGERTIP if obj.template == "button" else 0.
        self.grasps = obj.template != "button"
        self.rotation = axis_rotation((0, 0, 1), obj.yaw_rad)
        self.position = np.array(obj.position_m, float)

    def part_rotation(self, q):
        return axis_rotation(self.axis, q) if self.revolute else np.eye(3)

    def handle(self, q):
        """Handle center, approach direction and motion tangent in the robot base."""
        r = self.part_rotation(q)
        local = r @ self.handle0 if self.revolute else self.handle0+self.axis*q
        approach = self.rotation @ r @ self.approach0
        return (self.position+self.rotation @ local-approach*self.standoff, approach, self.rotation @ r @ self.tangent0)

    def grasp_rotation(self, q, flip=False):
        """Hand rotation: z approaches the bar, y (finger axis) is the motion tangent."""
        _, approach, tangent = self.handle(q)
        y = -tangent if flip else tangent
        return np.column_stack([np.cross(y, approach), y, approach])

    def elements(self, table_top=0.):
        obj = self.obj
        quat = [np.cos(obj.yaw_rad/2), 0, 0, np.sin(obj.yaw_rad/2)]  # MuJoCo wxyz
        fixture = ET.Element("body", name="proxy_fixture", pos=fmt(obj.position_m), quat=fmt(quat))
        part = ET.SubElement(fixture, "body", name="proxy_object", pos="0 0 0")
        joint = ET.SubElement(part, "joint", name="task_joint", type="hinge" if self.revolute else "slide", axis=fmt(self.axis),
            range=f"0 {obj.limit}", damping=str(obj.damping), frictionloss=str(obj.friction_loss), armature=".001")
        if obj.momentary:
            # Return spring; gravity compensation keeps the cap from sagging onto it.
            joint.set("stiffness", "60")
            part.set("gravcomp", "1")
        ET.SubElement(part, "site", name="task_handle", type="sphere", size=".008", rgba="1 .6 .1 1", pos=fmt(self.handle0))
        height = obj.position_m[2]-table_top
        getattr(self, "_"+obj.template)(fixture, part, height)
        return fixture

    def _lid(self, fixture, part, height):
        r, w = self.obj.radius_m, self.obj.width_m/2
        depth = r-FINGER_REACH  # the lip overhangs the base so a finger fits below it
        box(fixture, "fixture_base", [depth/2, 0, -.013], [depth/2, w, .008], ".2 .2 .22 1")
        desk = max(height-.021, .02)
        box(fixture, "fixture_desk", [(depth-.1)/2, 0, -.021-desk/2], [(depth+.1)/2, w+.05, desk/2], ".55 .45 .35 1")
        box(part, "part_panel", [(r+LID_OVERHANG)/2, 0, 0], [(r+LID_OVERHANG)/2, w, .004], ".3 .32 .36 1", self.obj.mass_kg)
        box(part, "part_handle", [r, 0, 0], [LID_OVERHANG, .05, .0045], "1 .6 .1 1", .005)

    def _door(self, fixture, part, height):
        r, half = self.obj.radius_m, .2
        length = r+.02  # handle near the free edge so the hand body clears the panel
        body = (height+half)/2
        box(fixture, "fixture_cabinet", [length/2, .17, half-body], [length/2+.02, .15, body], ".55 .45 .35 1")
        box(part, "part_panel", [length/2, 0, 0], [length/2, .01, half], ".3 .32 .36 1", self.obj.mass_kg)
        box(part, "part_handle", [r, -STANDOFF, 0], [.006, .006, .06], "1 .6 .1 1", .005)
        for z in (-.055, .055):
            box(part, f"part_post_{'a' if z < 0 else 'b'}", [r, -STANDOFF/2, z], [.005, STANDOFF/2, .005], "1 .6 .1 1", .002)

    def _knob(self, fixture, part, height):
        box(fixture, "fixture_panel", [0, 0, -.03-max(height-.03, .02)/2], [.09, .09, max(height-.03, .02)/2], ".55 .45 .35 1")
        box(part, "part_panel", [0, 0, -.018], [.008, .008, .012], ".3 .32 .36 1", self.obj.mass_kg)
        box(part, "part_handle", [0, 0, 0], [.006, .035, .012], "1 .6 .1 1", .01)

    def _button(self, fixture, part, height):
        base = self.obj.limit+.012
        box(fixture, "fixture_panel", [0, 0, -base-max(height-base, .02)/2], [.07, .07, max(height-base, .02)/2], ".55 .45 .35 1")
        box(part, "part_handle", [0, 0, -.006], [.02, .02, .006], "1 .3 .2 1", self.obj.mass_kg)

    def _drawer(self, fixture, part, height):
        w, top = self.obj.width_m/2, .02
        face = -STANDOFF-.008
        box(part, "part_handle", [0, 0, 0], [.006, .06, .006], "1 .6 .1 1", .005)
        for y in (-.055, .055):
            box(part, f"part_post_{'a' if y < 0 else 'b'}", [-STANDOFF/2, y, 0], [STANDOFF/2, .005, .005], "1 .6 .1 1", .002)
        box(part, "part_panel", [face, 0, top-.055], [.008, w, .055], ".3 .32 .36 1", self.obj.mass_kg)
        box(part, "part_tray", [face-.008-.12, 0, top-.055], [.12, w-.015, .045], ".42 .44 .48 1", .01)
        body = (height+top)/2
        box(fixture, "fixture_cabinet", [face-.01-.15, 0, top-body], [.15, w+.02, body], ".55 .45 .35 1")


def fmt(values):
    return " ".join(f"{float(v):.6g}" for v in values)


def box(parent, name, position, half_size, rgba, mass=None):
    # contype 0 / conaffinity 1: collides with the robot, never with other proxy geoms.
    geom = ET.SubElement(parent, "geom", name=name, type="box", pos=fmt(position), size=fmt(half_size), rgba=rgba,
        contype="0", conaffinity="1", friction="1 .005 .0001")
    if mass is not None:
        geom.set("mass", str(mass))
    return geom

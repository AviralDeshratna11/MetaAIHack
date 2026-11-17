"""Re-instantiate an inferred skill on the robot: scene, plan, variations.

The plan is derived from the generated object (its joint and handle, or its start
and goal), never from the demonstrated hand coordinates. Moving or resizing the
object therefore changes the robot motion while the process stays the same.

Three ways of acting are planned: grasp and follow a joint (lid, door, drawer,
knob), press with closed fingertips (button), and pick up and carry a free object.
"""
import numpy as np

from packages.common.utils import DomainError
from packages.robot.articulated import Articulation
from packages.schemas.replication import ArticulatedObject, ReplicationReport, TransportTask, VariationResult
from packages.schemas.robotization import RobotFrame, RobotTrajectory, TaskScene

# Canonical placements in the robot base (position of the object frame, yaw).
PLACEMENTS = {
    # A lid is approached in its own plane. The Panda holds a sideways horizontal
    # grasp across its workspace but not a forward one, so the lid opens across the robot.
    "lid": [([.5, .1, .28], -np.pi/2), ([.45, .12, .34], -np.pi/2), ([.55, .08, .25], -np.pi/2), ([.5, -.1, .28], np.pi/2)],
    "drawer": [([.56, 0, .3], np.pi), ([.52, 0, .34], np.pi), ([.6, 0, .26], np.pi)],
    "door": [([.6, .14, .4], -np.pi/2), ([.56, .12, .45], -np.pi/2), ([.64, .16, .36], -np.pi/2)],
    "knob": [([.5, 0, .25], 0.), ([.45, 0, .3], 0.), ([.55, .1, .2], 0.)],
    "button": [([.5, 0, .2], 0.), ([.45, .1, .25], 0.), ([.55, -.1, .15], 0.)],
}
ANGLE_LIMITS = {"lid": 1.92, "door": 1.3, "knob": 1.8}
IK_POSITION, IK_ROTATION, IK_JUMP = .003, .03, .6
SEEDS = [[0, -.4, 0, -1.9, 0, 1.5, .7854], [0, .2, 0, -2.2, 0, 2.4, .7854], [0, -.2, 0, -2.4, 0, 3.4, .7854],
         [0, .4, 0, -1.6, 0, 2., -.7854], [.4, .3, -.4, -1.9, .3, 2.2, 1.6], [-.4, .3, .4, -1.9, -.3, 2.2, 0]]
STAND_IN = {"Generated stand-in scene; the source object's dimensions and joint are not validated",
            "Grasp pose comes from the generated object; the human grasp is not replicated"}


def metric(config, hint):
    """Meters per reconstruction unit and where that number came from, or (None, default)."""
    if config.calibration.mode == "measured":
        return config.calibration.scale_m_per_unit, "measured_calibration"
    if hint and config.replication.use_video_scale and hint.get("scale_m_per_unit"):
        return hint["scale_m_per_unit"], hint["source"]
    return None, "template_default"


def build_task(skill, config, hint=None):
    """Generated task for a skill: an articulated object or a carried one. Returns (spec, reasons)."""
    template = skill.template if config.replication.template == "auto" else config.replication.template
    if template == "none":
        raise DomainError("E_SKILL_UNSUPPORTED", f"The demonstration looks {skill.kind}: no hinge, slide, press, twist or carried object was identified. "
            "Use trajectory mode, or set replication.template when the kind of object is known.", 409)
    reasons = []
    if config.replication.template != "auto" and template != skill.template:
        reasons.append(f"Template '{template}' was set explicitly; the demonstration suggested '{skill.template}'")
    scale, source = metric(config, hint)
    if scale and source != "measured_calibration":
        reasons.append(f"Lengths are scaled from the video by an estimate ({source.replace('_', ' ')}, {scale:.3f} m per unit); not a measurement")
    if template == "object":
        return build_transport(skill, config, scale, source, reasons)
    return build_object(skill, config, template, scale, source, reasons)


def build_object(skill, config, template=None, scale=None, source="template_default", reasons=None):
    """Joint amounts come from the demonstration; size from the video only when a scale is known."""
    options, reasons = config.replication, [] if reasons is None else reasons
    if template is None:
        return build_task(skill, config)
    direction = skill.direction if options.direction == "auto" else options.direction
    if direction == "unknown":
        direction = "open"
        reasons.append("Direction was undetermined; opening is assumed")
    revolute = template in ("lid", "door", "knob")
    radius, sized = options.default_radius_m, False
    if template == "knob":
        amount = clipped = options.default_twist_rad
        limit = clipped+.3
    elif template == "button":
        amount = clipped = options.default_press_m
        limit, direction = clipped+.006, "open"
    elif revolute:
        amount = abs(skill.displacement) if skill.kind == "revolute" else 1.
        if skill.kind != "revolute":
            reasons.append("No hinge angle was demonstrated; a 1.0 rad stand-in angle is used")
        clipped = float(np.clip(amount, options.min_angle_rad, ANGLE_LIMITS[template]))
        if scale and skill.radius_units:
            radius, sized = float(np.clip(skill.radius_units*scale, .1, .3)), True
            if abs(radius-skill.radius_units*scale) > 1e-6:
                reasons.append(f"Hinge-to-hand distance {skill.radius_units*scale:.2f} m from the video was limited to {radius:.2f} m")
        limit = clipped+.3
    else:
        sized = bool(scale) and skill.kind == "prismatic"
        amount = abs(skill.displacement)*scale if sized else options.default_travel_m
        clipped = float(np.clip(amount, .03, .25))
        limit = clipped+.04
        if not sized:
            reasons.append(f"Travel is not metric without a scale; {clipped:.2f} m is used")
    if abs(clipped-amount) > 1e-6:
        reasons.append(f"Demonstrated displacement {amount:.3f} was limited to {clipped:.3f} for the generated {template}")
    position, yaw = PLACEMENTS[template][0]
    physical = {"lid": (.1, .05, .15), "door": (.1, .05, .05), "drawer": (.3, 2., .3), "knob": (.02, .01, .005), "button": (.02, 1., 0.)}[template]
    return ArticulatedObject(template=template, joint="revolute" if revolute else "prismatic", momentary=template == "button",
        position_m=list(options.object_position_m or position), yaw_rad=float(yaw if options.object_yaw_rad is None else options.object_yaw_rad),
        radius_m=radius, start=0 if direction == "open" else clipped, goal=clipped if direction == "open" else 0, limit=limit,
        tolerance=(.35 if template == "button" else 1-options.success_fraction)*clipped, mass_kg=physical[0], damping=physical[1],
        friction_loss=physical[2], scale_source=source if sized else "template_default",
        placement_source="configured" if options.object_position_m else "canonical"), reasons


def build_transport(skill, config, scale, source, reasons):
    """Pick-and-carry task. Direction and proportions come from the demonstration."""
    options, carried = config.replication, skill.transport
    if carried is None:
        raise DomainError("E_SKILL_UNSUPPORTED", "No carried object was demonstrated; a free-object task needs a transport skill", 409)
    lengths = np.array([carried.horizontal_units, carried.rise_units, carried.peak_units])
    if scale:
        level, rise, peak = lengths*scale
    else:
        level, rise, peak = lengths*options.default_travel_m/max(np.abs(lengths).max(), 1e-9)
        reasons.append(f"Carry distance is not metric without a scale; the largest extent is set to {options.default_travel_m:.2f} m")
    if rise < -.015:
        reasons.append("The object ended lower than it started; the generated floor cannot go lower, so it ends at the start height")
    limited = (float(np.clip(level, 0, .3)), float(np.clip(rise, 0, .25)))
    if abs(limited[0]-level) > 1e-6 or rise > .25:
        reasons.append(f"Carry of {level:.2f} m across and {rise:.2f} m up was limited to {limited[0]:.2f} m and {limited[1]:.2f} m")
    level, rise = limited
    if carried.released and rise < .015:
        rise = 0.  # set back down on the same surface
    if not carried.released and rise < .04:
        rise = .04
        reasons.append("The object was still held but barely rose; a 4 cm lift is used so holding it is observable")
    if carried.released and level < .03 and rise == 0:
        raise DomainError("E_SKILL_UNSUPPORTED", "The object was put back where it started; there is no displacement to replicate", 409)
    lift = float(np.clip(max(peak, rise)+(.03 if carried.released else 0), max(.05, rise), .35))
    heading = carried.heading_rad
    if heading is None:
        heading = np.pi/2
        reasons.append("Carry direction relative to the reach is unknown; the object is carried sideways")
    move = [level*np.cos(heading), level*np.sin(heading), rise]
    half = TransportTask.model_fields["object_half_size_m"].default_factory()
    start = options.object_position_m or [.5-move[0]/2, -move[1]/2, half[2]]
    return TransportTask(object_position_m=list(start), displacement_m=move, lift_m=lift, release=carried.released,
        scale_source=source if scale else "template_default", placement_source="configured" if options.object_position_m else "canonical"), reasons


def measured_pose(skill, config, part):
    """Where the demonstration puts the object in the robot base, under measured calibration."""
    if config.calibration.mode != "measured" or skill.start_world is None or isinstance(part, TransportTask) or part.template in ("knob", "button"):
        return None
    transform = np.array(config.calibration.base_from_world)
    place = lambda p: config.calibration.scale_m_per_unit*transform[:3, :3] @ np.asarray(p, float)+transform[:3, 3]
    level = lambda v: np.array([v[0], v[1], 0.])
    start, end = place(skill.start_world), place(skill.end_world)
    rest = start if part.start == 0 else end  # handle position with the joint at zero
    if part.template == "drawer":
        opening = level(end-start)*(1 if part.start == 0 else -1)
        if np.linalg.norm(opening) < 1e-6:
            return None
        return rest.tolist(), float(np.arctan2(opening[1], opening[0]))
    if skill.origin_world is None:
        return None
    hinge = place(skill.origin_world)
    reach = level(rest-hinge)
    if np.linalg.norm(reach) < 1e-6:
        return None
    angle = np.arctan2(reach[1], reach[0])
    if part.template == "door":
        local = Articulation(part).handle0
        angle -= np.arctan2(local[1], local[0])
    return hinge.tolist(), float(angle)


class ArticulatedPlan:
    """Grasp a handle and follow the joint, or press it."""
    def __init__(self, part):
        self.spec, self.joint = part, Articulation(part)
        self.mode = "grasp" if self.joint.grasps else "press"
        self.release, self.values = True, (part.start, part.goal)
        self.label = part.template

    def scene(self, config):
        goal, _, _ = self.joint.handle(self.spec.goal)
        return TaskScene(task="articulated", articulation=self.spec, goal_position_m=goal.tolist(),
            evidence="Articulated stand-in generated from the inferred skill; not a reconstruction of the source object",
            goal_tolerance_m=.1, success_hold_s=config.replication.success_hold_s, horizon_s=120)

    def options(self):
        return [False, True]

    def stages(self, option, distance):
        part = self.spec
        span = part.goal-part.start
        step = np.deg2rad(4) if self.joint.revolute else .004 if part.momentary else .015
        count = int(np.clip(np.ceil(abs(span)/step), 4, 48))
        def pose(q, back):
            position, approach, _ = self.joint.handle(q)
            return position-approach*back, self.joint.grasp_rotation(q, option)
        return {"reach": [pose(part.start, distance*f) for f in np.linspace(1, 0, 5)],
                "manipulate": [pose(q, 0) for q in part.start+span*np.linspace(0, 1, count+1)],
                "retreat": [pose(part.goal, distance*f) for f in np.linspace(0, 1, 5)]}

    def vary(self, random, options):
        part = self.spec
        shift = random.uniform(-1, 1, 3)*[options.variation_position_m, options.variation_position_m, options.variation_position_m/2]
        return part.model_copy(update={"position_m": (np.array(part.position_m)+shift).tolist(),
            "yaw_rad": float(part.yaw_rad+random.uniform(-1, 1)*options.variation_yaw_rad),
            "radius_m": float(np.clip(part.radius_m*(1+random.uniform(-1, 1)*options.variation_scale), .1, .3))})

    def describe(self):
        part = self.spec
        return {"position_m": part.position_m, "yaw_rad": part.yaw_rad, "radius_m": part.radius_m, "goal": part.goal}

    def achieved(self, report):
        joint = report["task_joint"]
        return joint["start"]+joint["peak"]*np.sign(self.spec.goal-self.spec.start) if self.spec.momentary else joint["final"]

    def adaptation(self):
        part = self.spec
        return {"template": part.template, "joint": part.joint, "scale_source": part.scale_source, "placement_source": part.placement_source,
                "replicated_goal": part.goal, "replicated_start": part.start}


class TransportPlan:
    """Pick a free object up from above, carry it over an arch, and set it down or keep holding it."""
    GRIP_ABOVE_CENTER = .01  # keeps the hand body clear of the object's top

    def __init__(self, task):
        self.spec, self.mode, self.release, self.values = task, "grasp", task.release, (0., 0.)
        self.label = "object"

    def scene(self, config):
        task = self.spec
        goal = (np.array(task.object_position_m)+task.displacement_m).tolist()
        return TaskScene(task="pick_place", goal_position_m=goal, object_position_m=task.object_position_m,
            object_half_size_m=task.object_half_size_m, object_mass_kg=task.object_mass_kg, friction=1.,
            evidence="Free-object stand-in generated from the inferred carry; not a reconstruction of the source object",
            goal_tolerance_m=task.tolerance_m, required_lift_m=float(np.clip(.5*task.lift_m, .01, .3)),
            success_hold_s=config.replication.success_hold_s, hold_at_goal=not task.release,
            goal_support_m=task.displacement_m[2] if task.release else 0, horizon_s=120)

    def options(self):
        return [self.spec.grasp_yaw_rad, self.spec.grasp_yaw_rad+np.pi/2]

    def stages(self, option, distance):
        task = self.spec
        finger = np.array([np.cos(option), np.sin(option), 0.])
        down = np.array([0, 0, -1.])
        rotation = np.column_stack([np.cross(finger, down), finger, down])
        grasp = np.array(task.object_position_m)+[0, 0, self.GRIP_ABOVE_CENTER]
        move, up = np.array(task.displacement_m), np.array([0, 0, 1.])
        smooth = lambda u: (lambda c: 3*c**2-2*c**3)(np.clip(u, 0, 1))
        def carried(s):
            # Up first, across in the middle, down last: clears the support on both ends.
            height = task.lift_m*smooth(s/.3) if s < .5 else task.lift_m+(move[2]-task.lift_m)*smooth((s-.7)/.3)
            return grasp+smooth((s-.2)/.6)*move*[1, 1, 0]+height*up
        stages = {"reach": [(grasp+up*distance*f, rotation) for f in np.linspace(1, 0, 5)],
                  "manipulate": [(carried(s), rotation) for s in np.linspace(0, 1, 29)]}
        if task.release:
            stages["retreat"] = [(grasp+move+up*distance*f, rotation) for f in np.linspace(0, 1, 5)]
        return stages

    def vary(self, random, options):
        task = self.spec
        shift = random.uniform(-1, 1, 3)*[options.variation_position_m, options.variation_position_m, 0]
        turn = random.uniform(-1, 1)*options.variation_yaw_rad
        grow = 1+random.uniform(-1, 1)*options.variation_scale
        move = np.array(task.displacement_m)
        across = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]]) @ move[:2]*grow
        return task.model_copy(update={"object_position_m": (np.array(task.object_position_m)+shift).tolist(),
            "displacement_m": [float(across[0]), float(across[1]), float(move[2])]})

    def describe(self):
        task = self.spec
        move = np.array(task.displacement_m)
        return {"position_m": task.object_position_m, "yaw_rad": float(np.arctan2(move[1], move[0])),
                "radius_m": float(np.linalg.norm(move)), "goal": float(np.linalg.norm(move))}

    def achieved(self, report):
        return report["object_displacement_m"]

    def adaptation(self):
        task = self.spec
        return {"template": "object", "joint": "free", "scale_source": task.scale_source, "placement_source": task.placement_source,
                "replicated_goal": float(np.linalg.norm(task.displacement_m)), "replicated_start": 0., "release": task.release}


def adapter(spec):
    return TransportPlan(spec) if isinstance(spec, TransportTask) else ArticulatedPlan(spec)


def task_scene(spec, config):
    return adapter(spec).scene(config)


def solve(robot, position, rotation, seed, fallback):
    """Sequential IK. Where a discontinuity is acceptable, every seed is tried and
    the valid solution nearest the home posture wins, so the arm starts untwisted."""
    best = None
    for candidate in [seed, *(SEEDS if fallback else [])]:
        q, pe, re, collisions = robot.ik(position, rotation, np.asarray(candidate, float))
        valid = pe <= IK_POSITION and re <= IK_ROTATION and not collisions
        score = float(np.abs(q-robot.home).sum()) if valid else 100+pe+.1*re+bool(collisions)
        if best is None or score < best[0]:
            best = (score, q, pe, re, collisions)
        if valid and not fallback:
            break
    return best[1:]


def cartesian_chain(robot, task, options, option):
    """IK through every planned pose in order. Returns knots or the first failure reason."""
    task = task if hasattr(task, "stages") else adapter(task)
    previous, knots, travel = robot.home.copy(), {}, 0.
    for name, poses in task.stages(option, options.pregrasp_distance_m).items():
        knots[name] = []
        for index, (position, rotation) in enumerate(poses):
            first = name == "reach" and index == 0
            q, pe, re, collisions = solve(robot, position, rotation, previous, first)
            if pe > IK_POSITION or re > IK_ROTATION:
                return None, f"{name} pose {index} is out of reach (position error {pe*1000:.1f} mm, rotation error {re:.2f} rad)"
            if collisions:
                return None, f"{name} pose {index} is in self-collision ({', '.join(collisions)})"
            if not first and np.max(np.abs(q-previous)) > IK_JUMP:
                return None, f"{name} pose {index} needs a joint reconfiguration"
            travel += float(np.abs(q-previous).sum())
            knots[name].append({"q": q, "position": position, "rotation": rotation})
            previous = q
    return {"knots": knots, "travel": travel, "flip": option}, None


class Segment:
    """Joint path over s in [0,1] with a quintic time law that respects scaled limits."""
    def __init__(self, phase, knots, robot, options, config, gripper, minimum_s=0., dwell_s=None, cartesian=True, source=(0., 0.), joint=(0., 0.), touch=True):
        from scipy.interpolate import CubicSpline
        from scipy.spatial.transform import Rotation, Slerp
        self.phase, self.gripper, self.source, self.cartesian, self.joint, self.touch = phase, gripper, source, cartesian, joint, touch
        qs = np.array([k["q"] for k in knots])
        self.static = dwell_s is not None
        if self.static:
            self.duration, self.q0 = dwell_s, qs[0]
        else:
            if len(qs) == 2:  # a straight joint-space move
                qs = np.array([qs[0], (qs[0]+qs[1])/2, qs[1]])
            grid = np.linspace(0, 1, len(qs))
            self.spline = CubicSpline(grid, qs, bc_type="natural")
            if cartesian:
                self.positions = CubicSpline(grid, np.array([k["position"] for k in knots]))
                self.rotations = Slerp(grid, Rotation.from_matrix(np.array([k["rotation"] for k in knots])))
            dense = np.linspace(0, 1, 400)
            d1, d2 = np.abs(self.spline(dense, 1)).max(0), np.abs(self.spline(dense, 2)).max(0)
            fraction = options.limit_fraction
            limit = max(float(np.max(1.875*d1/(fraction*robot.velocity))),
                        float(np.max(np.sqrt((3.516*d2+5.774*d1)/(fraction*robot.acceleration)))), minimum_s, .8)
            self.duration = limit/config.execution_speed_scale
        self.duration = float(np.ceil(self.duration*config.control_hz-1e-9)/config.control_hz)

    def sample(self, u):
        if self.static:
            return 0., self.q0, np.zeros(7), np.zeros(7)
        s, sd, sdd = 10*u**3-15*u**4+6*u**5, (30*u**2-60*u**3+30*u**4)/self.duration, (60*u-180*u**2+120*u**3)/self.duration**2
        d1 = self.spline(s, 1)
        return s, self.spline(s), d1*sd, self.spline(s, 2)*sd**2+d1*sdd


class SceneCheck:
    """Kinematic contact check of a planned posture against the generated scene."""
    def __init__(self, robot, task, config):
        import mujoco as mj
        from packages.robot.scenes import scene_xml, task_joint
        self.mj, self.robot = mj, robot
        self.model = mj.MjModel.from_xml_string(scene_xml(robot.root, task.scene(config)))
        self.data = mj.MjData(self.model)
        self.qadr, self.joint = self.model.jnt_qposadr[robot.joints], task_joint(self.model)

    def contacts(self, q, width, joint_value, grasping):
        from packages.robot.scenes import forbidden_contacts
        self.data.qpos[self.qadr] = q
        self.data.qpos[7:9] = width/2
        if self.joint is not None:
            self.data.qpos[self.joint] = joint_value
        self.mj.mj_forward(self.model, self.data)
        return forbidden_contacts(self.model, self.data, allowed_grasp=grasping)


def approach_routes(robot, knots, options):
    """Joint-space approach, then detours that keep the hand clear of the object."""
    first = knots["reach"][0]
    approach = first["rotation"][:, 2]
    yield "direct", [{"q": robot.home.copy()}, first]
    outward = first["position"]*np.array([1, 1, 0])
    detours = {"from behind the grasp": -.18*approach, "from above": np.array([0, 0, .18]),
               "from the robot side": -.18*outward/max(np.linalg.norm(outward), 1e-9)}
    for name, offset in detours.items():
        q, pe, re, collisions = solve(robot, first["position"]+offset, first["rotation"], first["q"], False)
        if pe <= IK_POSITION and re <= IK_ROTATION and not collisions and np.max(np.abs(q-first["q"])) <= 1.5:
            yield name, [{"q": robot.home.copy()}, {"q": q}, first]


def sequence(task, knots, common, times, options):
    """Segments after the approach, for the task's way of acting."""
    t0, engage, release, t1 = times
    start, goal = task.values
    before, during, after = dict(source=(t0, engage), joint=(start, start)), dict(source=(engage, release), joint=(start, goal)), dict(source=(release, t1), joint=(goal, goal))
    grasp, done = [knots["reach"][-1]], [knots["manipulate"][-1]]
    hold = options.success_hold_s+.5
    if task.mode == "press":
        return [Segment("reach", knots["reach"], *common, "closed", **before),
                Segment("manipulate", knots["manipulate"], *common, "closed", minimum_s=release-engage, **during),
                Segment("settle", done, *common, "closed", dwell_s=.3, **after),
                Segment("retreat", knots["retreat"], *common, "closed", **after),
                Segment("hold", [knots["retreat"][-1]], *common, "closed", dwell_s=hold, touch=False, **after)]
    body = [Segment("reach", knots["reach"], *common, "open", **before),
            Segment("grasp", grasp, *common, "closed", dwell_s=options.grasp_dwell_s, **before),
            Segment("manipulate", knots["manipulate"], *common, "hold", minimum_s=release-engage, **during)]
    if not task.release:
        return body+[Segment("hold", done, *common, "hold", dwell_s=hold, **after)]
    return body+[Segment("settle", done, *common, "hold", dwell_s=.3, **after),
                 Segment("release", done, *common, "open", dwell_s=options.grasp_dwell_s, **after),
                 Segment("retreat", knots["retreat"], *common, "open", **after),
                 Segment("hold", [knots["retreat"][-1]], *common, "open", dwell_s=hold, touch=False, **after)]


def plan(skill, spec, config, robot, run_id, itr, review=()):
    """Approach, act on the generated object by the demonstrated amount, and let go or hold."""
    options, task = config.replication, adapter(spec)
    chains = [cartesian_chain(robot, task, options, option) for option in task.options()]
    failures = sorted({reason for _, reason in chains if reason})
    checker = SceneCheck(robot, task, config)
    phases = {p.name: p for p in skill.phases}
    times = (phases["approach"].start_s, phases["manipulate"].start_s, phases["manipulate"].end_s, phases["retreat"].end_s)
    common = (robot, options, config)
    first_grip = "closed" if task.mode == "press" else "open"
    for chain in sorted((c for c, _ in chains if c), key=lambda c: c["travel"]):
        knots = chain["knots"]
        body = sequence(task, knots, common, times, options)
        for route, waypoints in approach_routes(robot, knots, options):
            segments = [Segment("approach", waypoints, *common, first_grip, cartesian=False, source=(times[0], times[1]),
                                joint=(task.values[0], task.values[0]), touch=False), *body]
            frames, total, starts, blocked = timeline(segments, skill, config, robot, itr, checker)
            if blocked:
                failures.append(f"{route} approach: {blocked}")
                continue
            scene = task.scene(config)
            scene.horizon_s = min(120., total+2)
            adaptation = {"mode": "skill_replication", "metric_reconstruction": config.calibration.mode == "measured",
                "evidence": config.calibration.evidence, "target_source": "Generated object; demonstrated hand coordinates are not replayed",
                **task.adaptation(), "action": task.mode, "grasp_option": float(chain["flip"]), "approach_route": route,
                "demonstrated_displacement": skill.displacement, "displacement_unit": skill.displacement_unit, "execution_duration_s": total,
                "requested_interval_s": [config.start_s, config.end_s], "observed_interval_s": [times[0], times[3]],
                "execution_speed_scale": config.execution_speed_scale,
                "phases": [{"phase": s.phase, "start_s": float(starts[i]), "duration_s": s.duration} for i, s in enumerate(segments)]}
            issues = set(review) | set(skill.review_reasons) | set(getattr(itr.quality, "review_reasons", [])) | STAND_IN
            return RobotTrajectory(video_id=itr.video_id, run_id=run_id, source_run_id=itr.run_id, task=itr.task,
                inference_mode=itr.quality.inference_mode, robot=robot.spec, config=config.model_copy(update={"task_scene": scene}),
                adaptation=adaptation, review_reasons=sorted(issues), frames=frames)
    raise DomainError("E_SKILL_UNREACHABLE", "; ".join(failures), 409)


def timeline(segments, skill, config, robot, itr, checker):
    """Sample every control tick. Returns frames, or the first scene contact that blocks the plan."""
    from scipy.spatial.transform import Rotation
    starts = np.cumsum([0]+[s.duration for s in segments])
    total = float(starts[-1])
    if total*config.control_hz > 100000:
        raise DomainError("E_ROBOT_DURATION", "Planned replication exceeds frame quota")
    # Source time: the same share of each demonstrated phase, and the same
    # progress during manipulation, so the source/execution map stays meaningful.
    group = {"approach": 0, "reach": 0, "grasp": 0, "manipulate": 1, "settle": 2, "release": 2, "retreat": 2, "hold": 2}
    spans = {g: (min(starts[i] for i, s in enumerate(segments) if group[s.phase] == g),
                 max(starts[i+1] for i, s in enumerate(segments) if group[s.phase] == g)) for g in (0, 1, 2)}
    source_frames = sorted((f.timestamp, f.frame_index) for f in itr.frames if f.shot_id == config.shot_id and config.start_s <= f.timestamp <= config.end_s)
    width = config.open_width_m if segments[0].gripper == "open" else config.closed_width_m
    output = []
    for index in range(int(round(total*config.control_hz))+1):
        t = index/config.control_hz
        number = min(int(np.searchsorted(starts, t+1e-9, side="right"))-1, len(segments)-1)
        segment = segments[number]
        u = float(np.clip((t-starts[number])/segment.duration, 0, 1))
        s, q, velocity, acceleration = segment.sample(u)
        lo, hi = spans[group[segment.phase]]
        if segment.phase == "manipulate" and len(skill.progress) >= 2 and skill.progress[-1] > 0:
            source_t = float(np.interp(s, skill.progress, skill.progress_times_s))
        else:
            source_t = float(segment.source[0]+(t-lo)/max(hi-lo, 1e-9)*(segment.source[1]-segment.source[0]))
        desired = config.open_width_m if segment.gripper == "open" else config.closed_width_m
        bound = config.max_gripper_speed_m_s/config.control_hz
        width += float(np.clip(desired-width, -bound, bound))
        # Only the fingers may touch the object, and only between reach and letting go.
        touching = checker.contacts(q, width, segment.joint[0]+s*(segment.joint[1]-segment.joint[0]), segment.touch)
        if touching:
            return None, total, starts, f"{segment.phase} at {t:.2f}s touches {', '.join(touching)}"
        robot.set_gripper(width)
        achieved, rotation = robot.fk(q)
        if segment.static or not segment.cartesian:
            target, target_rotation = achieved, rotation
        else:
            target, target_rotation = segment.positions(s), segment.rotations(s).as_matrix()
        pe, re = float(np.linalg.norm(achieved-target)), float(Rotation.from_matrix(target_rotation @ rotation.T).magnitude())
        collisions, reasons = robot.collisions(), []
        if pe > config.position_tolerance_m: reasons.append("INTERPOLATED_TCP_ERROR")
        if re > config.orientation_tolerance_rad: reasons.append("INTERPOLATED_ORIENTATION_ERROR")
        if collisions: reasons.append("SELF_COLLISION")
        if np.any(np.abs(velocity) > robot.velocity+1e-6): reasons.append("VELOCITY_LIMIT")
        if np.any(np.abs(acceleration) > robot.acceleration+1e-6): reasons.append("ACCELERATION_LIMIT")
        frame_index = max((f for f in source_frames if f[0] <= source_t+1e-8), default=source_frames[0])[1]
        quaternion = Rotation.from_matrix(target_rotation).as_quat()
        output.append(RobotFrame(frame_index=frame_index, source_time_s=source_t, execution_time_s=t,
            target_position_m=np.asarray(target).tolist(), achieved_position_m=achieved.tolist(),
            target_quaternion_xyzw=(quaternion/np.linalg.norm(quaternion)).tolist(), joints_rad=np.asarray(q).tolist(),
            velocity_rad_s=np.asarray(velocity).tolist(), acceleration_rad_s2=np.asarray(acceleration).tolist(),
            gripper_width_m=width, gripper_state=segment.gripper, position_error_m=pe, orientation_error_rad=re,
            collisions=collisions, valid=not reasons, reasons=sorted(reasons), origin="planned", phase=segment.phase))
    return output, total, starts, None


def replicate(itr, config, robot, run_id, hint=None, semantics=None):
    """Skill -> generated task -> first reachable placement -> plan."""
    from packages.robot.skill import extract_skill
    if config.robot_id != robot.spec.get("robot_id", "panda"):
        raise DomainError("E_ROBOT_MODEL", "Selected robot does not match the pinned asset model", 409)
    skill = extract_skill(itr, config, semantics)
    spec, reasons = build_task(skill, config, hint)
    if isinstance(spec, TransportTask) or config.replication.object_position_m is not None:
        return plan(skill, spec, config, robot, run_id, itr, reasons), skill, spec, f"{spec.placement_source} placement"
    candidates = [("canonical", position, yaw) for position, yaw in PLACEMENTS[spec.template]]
    seen = measured_pose(skill, config, spec)
    if seen:
        candidates.insert(0, ("measured_calibration", *seen))
    failures = []
    for number, (origin, position, yaw) in enumerate(candidates):
        candidate = spec.model_copy(update={"position_m": list(position), "yaw_rad": float(yaw), "placement_source": origin})
        notes = list(reasons)
        if seen and origin == "canonical":
            notes.append("The placement measured from the video is not reachable by this robot; a canonical placement is used")
        try:
            trajectory = plan(skill, candidate, config, robot, run_id, itr, notes)
        except (DomainError, ValueError) as exc:
            if isinstance(exc, DomainError) and exc.code != "E_SKILL_UNREACHABLE":
                raise
            failures.append(str(exc))
            continue
        label = "placement measured from the video" if origin == "measured_calibration" else f"canonical {candidate.template} placement {number+1-bool(seen)} of {len(PLACEMENTS[spec.template])}"
        return trajectory, skill, candidate, label
    raise DomainError("E_SKILL_UNREACHABLE", "No placement of the generated object is reachable: "+" | ".join(failures), 409)


def variations(skill, spec, config, robot, assets, run_id, itr):
    """Same skill, moved and resized object. Each case is re-planned and re-simulated."""
    import tempfile
    from packages.robot.simulation import replay
    options, results = config.replication, []
    random = np.random.default_rng(options.variation_seed)
    for index in range(options.variations):
        changed = adapter(adapter(spec).vary(random, options))
        base = {"index": index, **changed.describe()}
        try:
            trajectory = plan(skill, changed.spec, config, robot, f"{run_id}-variation-{index}", itr)
        except DomainError as exc:
            results.append(VariationResult(**base, planned=False, success=False, violations=[], reason=str(exc)))
            continue
        with tempfile.TemporaryDirectory() as directory:
            report = replay(trajectory, assets, directory, render=False)
        success = bool(report["simulation_task_success"])
        results.append(VariationResult(**base, planned=True, success=success, final_joint=float(changed.achieved(report)), violations=report["violations"],
            reason=None if success else "Checked violation during execution" if report["violations"] else "The simulated object did not end where the demonstration put it"))
    return results


def summarize(run_id, itr, skill, spec, placement, trajectory, simulation, results, hint=None):
    """What was demonstrated, what the robot did in simulation, and how it held up when the scene changed."""
    task = adapter(spec)
    planned = task.describe()["goal"] if isinstance(spec, TransportTask) else abs(spec.goal-spec.start)
    if isinstance(spec, TransportTask):
        moved = simulation.get("object_displacement_m")
    else:
        joint = simulation.get("task_joint") or {}
        moved = None if not joint else joint["peak"] if spec.momentary else abs(joint["final"]-joint["start"])
    return ReplicationReport(run_id=run_id, source_run_id=itr.run_id, skill=skill, scene=None if isinstance(spec, TransportTask) else spec,
        transport=spec if isinstance(spec, TransportTask) else None, metric_scale=hint, placement=placement,
        demonstrated_displacement=abs(skill.displacement), replicated_displacement=moved,
        replicated_fraction=None if moved is None or planned <= 0 else moved/planned, simulation_task_success=simulation.get("simulation_task_success"),
        phases=trajectory.adaptation["phases"], variations=results,
        variation_success_rate=sum(r.success for r in results)/len(results) if results else None,
        review_reasons=trajectory.review_reasons)


def readiness(itr, config, semantics=None):
    """Cheap pre-submission check: can a supported skill be inferred from this interval?"""
    from packages.robot.skill import extract_skill
    meaning = "Skill inference only; reachability and physics are checked when the job runs"
    try:
        skill = extract_skill(itr, config, semantics)
        build_task(skill, config)
    except DomainError as exc:
        return {"ready_for_ik_attempt": False, "paired_samples": 0, "reasons": [exc.message], "skill": None, "meaning": meaning}
    return {"ready_for_ik_attempt": True, "paired_samples": skill.samples, "reasons": [], "skill": skill.model_dump(mode="json"), "meaning": meaning}

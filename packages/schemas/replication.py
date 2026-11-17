"""Phase 4 contracts: object-centric skill replication.

A skill is the *process* observed in a demonstration (which part moved, about
which joint, in which direction, by how much, in what order), not its absolute
hand coordinates. Lengths in a skill are in reconstruction units unless a field
name ends in ``_m``. Robot-side quantities are meters/radians; quaternions xyzw.
"""
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from packages.schemas.models import Contract, Time
from packages.schemas.reconstruction import Vec3

Unit = Annotated[FiniteFloat, Field(ge=0, le=1)]
NonNegative = Annotated[FiniteFloat, Field(ge=0)]


class ReplicationContract(Contract):
    schema_version: Literal["0.4.0"] = "0.4.0"


class MotionFit(ReplicationContract):
    """One candidate explanation of the contact-phase motion."""
    kind: Literal["static", "prismatic", "revolute"]
    # Root-mean-square residual divided by the path extent (scale free).
    relative_rmse: NonNegative
    bic: FiniteFloat
    parameters: int = Field(ge=0)


class SkillPhase(ReplicationContract):
    name: Literal["approach", "manipulate", "retreat"]
    start_s: Time
    end_s: Time
    samples: int = Field(ge=0)


class TransportSkill(ReplicationContract):
    """A carried object: where it went relative to gravity and to the reach."""
    # Reconstruction units along the up hint and in the plane normal to it.
    horizontal_units: NonNegative
    rise_units: FiniteFloat
    peak_units: NonNegative
    # Signed angle about up from the reach direction to the horizontal displacement.
    heading_rad: FiniteFloat | None = None
    released: bool


class SkillModel(ReplicationContract):
    """What was demonstrated, expressed relative to the manipulated part."""
    hand_id: str
    object_id: str
    shot_id: str
    kind: Literal["revolute", "prismatic", "static", "transport", "unconstrained"]
    transport: TransportSkill | None = None
    # First and last manipulation samples (demonstration world).
    start_world: Vec3 | None = None
    end_world: Vec3 | None = None
    # Demonstration world frame (relative scale). Axis follows the right-hand
    # rule for the observed motion; origin is a point on a revolute axis.
    axis_world: Vec3 | None = None
    origin_world: Vec3 | None = None
    radius_units: NonNegative | None = None
    # Signed joint displacement: radians (scale free) or reconstruction units.
    displacement: FiniteFloat = 0
    displacement_unit: Literal["rad", "reconstruction_units", "none"] = "none"
    # Process descriptors that survive a change of scene, scale and viewpoint.
    direction: Literal["open", "close", "unknown"] = "unknown"
    direction_evidence: str
    axis_alignment: Literal["horizontal", "vertical", "oblique", "unknown"] = "unknown"
    approach_alignment: FiniteFloat | None = None
    template: Literal["lid", "door", "drawer", "knob", "button", "object", "none"]
    # Monotone demonstrated progress (0..1) against source time.
    progress_times_s: list[Time]
    progress: list[Unit]
    phases: list[SkillPhase]
    fits: list[MotionFit]
    samples: int = Field(ge=0)
    contact_samples: int = Field(ge=0)
    motion_source: Literal["hand_during_contact", "hand_during_planned_action", "object", "hand_whole_interval"]
    confidence: Unit
    semantic_hint: str | None = None
    review_reasons: list[str]

    @model_validator(mode="after")
    def consistent(self):
        if len(self.progress_times_s) != len(self.progress):
            raise ValueError("progress profile lengths differ")
        if any(b < a-1e-9 for a, b in zip(self.progress, self.progress[1:])):
            raise ValueError("progress must be monotone")
        if self.kind in ("revolute", "prismatic") and self.axis_world is None:
            raise ValueError("articulated skill requires an axis")
        if (self.kind == "transport") != (self.transport is not None):
            raise ValueError("transport descriptors are required for, and only valid with, a transport skill")
        return self


class ArticulatedObject(ReplicationContract):
    """Simulated stand-in generated from a skill. Not a reconstruction of the source object."""
    template: Literal["lid", "door", "drawer", "knob", "button"]
    joint: Literal["revolute", "prismatic"]
    # A momentary part (button) springs back; success is having reached the goal.
    momentary: bool = False
    # Pose of the object frame in the robot base: position and yaw about +z.
    position_m: Vec3
    yaw_rad: FiniteFloat = 0
    # Hinge-to-handle distance (revolute) or unused (prismatic).
    radius_m: Annotated[FiniteFloat, Field(ge=.08, le=.4)] = .2
    width_m: Annotated[FiniteFloat, Field(ge=.1, le=.6)] = .3
    # Joint values: radians or meters. The joint range is [0, limit].
    start: NonNegative = 0
    goal: NonNegative
    limit: Annotated[FiniteFloat, Field(gt=0)]
    tolerance: Annotated[FiniteFloat, Field(gt=0)]
    mass_kg: Annotated[FiniteFloat, Field(gt=0, le=5)] = .1
    damping: NonNegative = .05
    friction_loss: NonNegative = .15
    scale_source: Literal["measured_calibration", "body_scale_estimate", "hand_extent_estimate", "template_default"]
    placement_source: Literal["canonical", "configured", "measured_calibration"] = "canonical"

    @model_validator(mode="after")
    def bounded(self):
        if max(self.start, self.goal) > self.limit+1e-9:
            raise ValueError("joint start/goal exceed the joint limit")
        if abs(self.goal-self.start) <= self.tolerance:
            raise ValueError("goal is within tolerance of the start; nothing to replicate")
        if (self.joint == "prismatic") != (self.template in ("drawer", "button")):
            raise ValueError("template and joint type disagree")
        if self.momentary != (self.template == "button"):
            raise ValueError("only a button is momentary")
        return self


class TransportTask(ReplicationContract):
    """Generated pick-and-carry task. The box is a stand-in for the carried object."""
    object_position_m: Vec3
    object_half_size_m: Vec3 = Field(default_factory=lambda: [.025, .025, .035])
    object_mass_kg: Annotated[FiniteFloat, Field(gt=0, le=1)] = .05
    grasp_yaw_rad: FiniteFloat = 1.5707963267948966
    # Object-center displacement in the robot base, and carry clearance above the start.
    displacement_m: Vec3
    lift_m: Annotated[FiniteFloat, Field(ge=.03, le=.4)]
    # False when the demonstration ends with the object still held.
    release: bool
    tolerance_m: Annotated[FiniteFloat, Field(gt=0, le=.1)] = .03
    scale_source: Literal["measured_calibration", "body_scale_estimate", "hand_extent_estimate", "template_default"]
    placement_source: Literal["canonical", "configured", "measured_calibration"] = "canonical"

    @model_validator(mode="after")
    def feasible(self):
        if self.displacement_m[2] < -1e-9:
            raise ValueError("the generated support is the floor; the object cannot end below its start")
        if self.lift_m < self.displacement_m[2]-1e-9:
            raise ValueError("carry clearance is below the goal height")
        return self


class ReplicationConfig(ReplicationContract):
    """How a skill is re-instantiated on the robot."""
    # Overrides; "auto" uses what the demonstration supports.
    template: Literal["auto", "lid", "door", "drawer", "knob", "button", "object"] = "auto"
    direction: Literal["auto", "open", "close"] = "auto"
    # OpenCV-style reconstruction worlds have +y pointing down in the first camera.
    up_hint_world: Vec3 = Field(default_factory=lambda: [0, -1, 0])
    # Used when no measured calibration supplies metric size.
    default_radius_m: Annotated[FiniteFloat, Field(ge=.1, le=.3)] = .18
    default_travel_m: Annotated[FiniteFloat, Field(ge=.03, le=.25)] = .15
    # A twist or a press leaves no measurable hand translation; these are declared.
    default_twist_rad: Annotated[FiniteFloat, Field(ge=.3, le=1.8)] = 1.5707963267948966
    default_press_m: Annotated[FiniteFloat, Field(ge=.004, le=.03)] = .012
    # Size the scene from the video using the body model's metric skeleton when available.
    use_video_scale: bool = True
    object_position_m: Vec3 | None = None
    object_yaw_rad: FiniteFloat | None = None
    min_angle_rad: Annotated[FiniteFloat, Field(gt=0, le=1)] = .2
    pregrasp_distance_m: Annotated[FiniteFloat, Field(ge=.03, le=.2)] = .08
    grasp_dwell_s: Annotated[FiniteFloat, Field(ge=.2, le=5)] = 1.
    limit_fraction: Annotated[FiniteFloat, Field(gt=0, le=1)] = .3
    success_fraction: Annotated[FiniteFloat, Field(gt=.5, le=1)] = .85
    success_hold_s: Annotated[FiniteFloat, Field(gt=0, le=2)] = .3
    # Robustness: re-plan and re-simulate with the object moved/resized.
    variations: int = Field(4, ge=0, le=32)
    variation_seed: int = Field(0, ge=0)
    variation_position_m: Annotated[FiniteFloat, Field(ge=0, le=.1)] = .03
    variation_yaw_rad: Annotated[FiniteFloat, Field(ge=0, le=.5)] = .15
    variation_scale: Annotated[FiniteFloat, Field(ge=0, le=.3)] = .1


class VariationResult(ReplicationContract):
    index: int = Field(ge=0)
    position_m: Vec3
    yaw_rad: FiniteFloat
    radius_m: FiniteFloat
    planned: bool
    success: bool
    final_joint: FiniteFloat | None = None
    goal: FiniteFloat
    violations: list[str]
    reason: str | None = None


class ReplicationReport(ReplicationContract):
    run_id: str
    source_run_id: str
    skill: SkillModel
    scene: ArticulatedObject | None = None
    transport: TransportTask | None = None
    # How lengths in the video were converted to meters, if they were.
    metric_scale: dict | None = None
    scene_source: Literal["generated_from_skill_template"] = "generated_from_skill_template"
    placement: str
    demonstrated_displacement: FiniteFloat
    replicated_displacement: FiniteFloat | None = None
    replicated_fraction: FiniteFloat | None = None
    simulation_task_success: bool | None = None
    phases: list[dict]
    variations: list[VariationResult]
    variation_success_rate: Unit | None = None
    # A generated stand-in scene can show the process is executable; it cannot
    # certify the original object, its dimensions or a physical robot.
    source_task_validated: Literal[False] = False
    physical_robot_ready: Literal[False] = False
    review_reasons: list[str]

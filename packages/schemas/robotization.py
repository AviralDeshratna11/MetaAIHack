"""Phase 3 contracts. Robot coordinates are meters/radians; quaternions are xyzw."""
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, FiniteFloat, model_validator

from packages.schemas.models import Contract
from packages.schemas.reconstruction import Vec3, Quat

Joint7 = Annotated[list[FiniteFloat], Field(min_length=7, max_length=7)]
Positive = Annotated[FiniteFloat, Field(gt=0)]


class RobotContract(Contract):
    schema_version: Literal["0.3.0"] = "0.3.0"


class Calibration(RobotContract):
    mode: Literal["measured", "workspace_adaptation"] = "workspace_adaptation"
    scale_m_per_unit: Positive = 1
    base_from_world: list[list[FiniteFloat]] = Field(default_factory=lambda: np.eye(4).tolist())
    evidence: str = Field(min_length=1)
    # A measured scale does not alone establish grasp or task validity.
    residual_m: Annotated[FiniteFloat, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def rigid(self):
        t = np.asarray(self.base_from_world)
        if t.shape != (4, 4) or not np.allclose(t[3], [0, 0, 0, 1]) or not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(t[:3, :3]), 1):
            raise ValueError("base_from_world must be SE(3)")
        if self.mode == "measured" and self.residual_m is None:
            raise ValueError("measured calibration requires residual_m")
        return self


class TaskScene(RobotContract):
    task: Literal["reach", "pick_place"]
    geometry_source: Literal["configured_simulation_proxy", "measured_task_scene"] = "configured_simulation_proxy"
    evidence: str = Field(min_length=1)
    goal_position_m: Vec3
    object_position_m: Vec3 = Field(default_factory=lambda: [.5, 0, .035])
    object_half_size_m: Vec3 = Field(default_factory=lambda: [.02, .02, .035])
    object_mass_kg: Annotated[FiniteFloat, Field(gt=0, le=10)] = .1
    friction: Annotated[FiniteFloat, Field(gt=0, le=5)] = .8
    table_top_m: FiniteFloat = 0
    goal_tolerance_m: Annotated[FiniteFloat, Field(gt=0, le=.1)] = .025
    required_lift_m: Annotated[FiniteFloat, Field(gt=0, le=.3)] = .04
    success_hold_s: Annotated[FiniteFloat, Field(gt=0, le=2)] = .2
    horizon_s: Annotated[FiniteFloat, Field(gt=0, le=120)] = 15

    @model_validator(mode="after")
    def geometry(self):
        if any(x <= 0 or x > .3 for x in self.object_half_size_m):
            raise ValueError("Object half sizes must be positive and at most 0.3 meters")
        if self.object_position_m[2]-self.object_half_size_m[2] < self.table_top_m-1e-5:
            raise ValueError("Object initial position intersects support surface")
        if self.task == "pick_place" and self.goal_position_m[2] < self.table_top_m:
            raise ValueError("Placement goal must be above support surface")
        return self


class RobotizationConfig(RobotContract):
    hand_id: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    start_s: Annotated[FiniteFloat, Field(ge=0)] = 0
    end_s: Positive = 120
    calibration: Calibration = Field(default_factory=lambda: Calibration(evidence="Automatic workspace adaptation; unknown physical dimensions"))
    workspace_center_m: Vec3 = Field(default_factory=lambda: [.45, 0, .4])
    workspace_extent_m: Annotated[FiniteFloat, Field(gt=0, le=.4)] = .18
    tcp_quaternion_xyzw: Quat = Field(default_factory=lambda: [1, 0, 0, 0])
    tcp_offset_m: Vec3 = Field(default_factory=lambda: [0, 0, 0])
    orientation_source: Literal["configured_task_constraint"] = "configured_task_constraint"
    max_gap_s: Annotated[FiniteFloat, Field(gt=0, le=1)] = .3
    control_hz: int = Field(30, ge=5, le=120)
    execution_speed_scale: Annotated[FiniteFloat, Field(gt=0, le=1)] = 1
    final_hold_s: Annotated[FiniteFloat, Field(ge=0, le=5)] = 0
    position_tolerance_m: Positive = .015
    orientation_tolerance_rad: Positive = .15
    simulation_tracking_tolerance_m: Positive = .04
    initial_gripper: Literal["open", "closed", "unknown"] = "unknown"
    open_width_m: Annotated[FiniteFloat, Field(ge=0, le=.08)] = .08
    closed_width_m: Annotated[FiniteFloat, Field(ge=0, le=.08)] = 0
    max_gripper_speed_m_s: Positive = .1
    require_export: bool = True
    diagnostic_export: bool = True
    task_scene: TaskScene | None = None
    # Frozen rubric; changes are part of config/hash and do not alter old results.
    quality_rubric: Literal["baseline-v1"] = "baseline-v1"

    @model_validator(mode="after")
    def interval(self):
        if self.end_s <= self.start_s:
            raise ValueError("end_s must exceed start_s")
        if not np.isclose(np.linalg.norm(self.tcp_quaternion_xyzw), 1, atol=1e-6):
            raise ValueError("TCP quaternion must have unit norm")
        if self.closed_width_m > self.open_width_m:
            raise ValueError("closed width exceeds open width")
        return self


class RobotizationRequest(RobotContract):
    source_job_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    config: RobotizationConfig
    allow_review_source: bool = False


class RobotFrame(RobotContract):
    frame_index: int = Field(ge=0)
    source_time_s: Annotated[FiniteFloat, Field(ge=0)]
    execution_time_s: Annotated[FiniteFloat, Field(ge=0)]
    target_position_m: Vec3
    achieved_position_m: Vec3
    target_quaternion_xyzw: Quat
    joints_rad: Joint7
    velocity_rad_s: Joint7
    acceleration_rad_s2: Joint7
    gripper_width_m: Annotated[FiniteFloat, Field(ge=0, le=.08)] | None
    gripper_state: Literal["open", "closed", "hold", "unknown"]
    position_error_m: Annotated[FiniteFloat, Field(ge=0)]
    orientation_error_rad: Annotated[FiniteFloat, Field(ge=0)]
    collisions: list[str]
    valid: bool
    reasons: list[str]
    origin: Literal["retargeted", "interpolated"]


class RobotTrajectory(RobotContract):
    video_id: str
    run_id: str
    source_run_id: str
    task: str
    inference_mode: Literal["live", "fixture"]
    robot: dict
    config: RobotizationConfig
    adaptation: dict
    review_reasons: list[str]
    frames: list[RobotFrame]


class QualityReport(RobotContract):
    classification: Literal["Gold", "Silver", "Reject"]
    rubric: Literal["baseline-v1"] = "baseline-v1"
    checks: dict[str, bool | None]
    reasons: list[str]
    accepted_training_subset: bool
    physical_robot_ready: Literal[False] = False


class RobotizationHandoff(RobotContract):
    video_id: str
    run_id: str
    source_run_id: str
    inference_mode: Literal["fixture", "live"]
    artifacts: dict[str, str]
    quality: QualityReport
    certification: Literal["simulation_and_export_report"] = "simulation_and_export_report"

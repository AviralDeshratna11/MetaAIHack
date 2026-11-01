"""Module B contracts. All transforms map source coordinates into target coordinates."""
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, FiniteFloat, model_validator

from packages.schemas.models import ActionGraph, Confidence, Contract, Entity, Primitive, Time, Vec2

Vec3 = Annotated[list[FiniteFloat], Field(min_length=3, max_length=3)]
Quat = Annotated[list[FiniteFloat], Field(min_length=4, max_length=4)]


class ReconstructionContract(Contract):
    schema_version: Literal["0.2.0"] = "0.2.0"


class ReconstructionConfig(ReconstructionContract):
    backend: Literal["fixture", "vggt"] = "fixture"
    body_backend: Literal["none", "sam3d"] = "none"
    sample_fps: Annotated[FiniteFloat, Field(gt=0, le=10)] = 5
    max_frames_per_shot: int = Field(32, ge=2, le=96)
    max_total_frames: int = Field(96, ge=2, le=512)
    max_points_per_entity: int = Field(256, ge=16, le=2048)
    contact_distance_2d_px: Annotated[FiniteFloat, Field(gt=0)] = 12
    contact_distance_3d_relative: Annotated[FiniteFloat, Field(gt=0)] = .04
    contact_on: Confidence = .72
    contact_off: Confidence = .4
    persistence_frames: int = Field(3, ge=2, le=30)
    boundary_window_s: Annotated[FiniteFloat, Field(gt=0, le=5)] = 1.5
    max_alignment_relative_rmse: Annotated[FiniteFloat, Field(gt=0, le=1)] = .08

    @model_validator(mode="after")
    def thresholds(self):
        if self.contact_on <= self.contact_off:
            raise ValueError("contact_on must exceed contact_off for hysteresis")
        return self


class ReconstructionRequest(ReconstructionContract):
    source_job_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    config: ReconstructionConfig = Field(default_factory=ReconstructionConfig)
    allow_review_source: bool = False


class Pose3D(ReconstructionContract):
    position_xyz: Vec3
    quaternion_xyzw: Quat | None = None
    confidence: Confidence | None = None
    metric_scale_valid: Literal[False] = False

    @model_validator(mode="after")
    def quaternion(self):
        if self.quaternion_xyzw is not None and abs(np.linalg.norm(self.quaternion_xyzw) - 1) > 1e-5:
            raise ValueError("quaternion_xyzw must have unit norm")
        return self


class Alignment(ReconstructionContract):
    alignment_id: str
    source_frame: str
    target_frame: str
    rotation: list[Vec3]
    translation: Vec3
    scale: Annotated[FiniteFloat, Field(gt=0)]
    rmse: Time
    correspondence_count: int = Field(ge=3)
    method: str
    uncertainty: str = "uncalibrated; correspondence residual only"

    @model_validator(mode="after")
    def rotation_matrix(self):
        r = np.asarray(self.rotation)
        if r.shape != (3, 3) or not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or np.linalg.det(r) < .9999:
            raise ValueError("alignment rotation must be a proper 3x3 rotation")
        return self


class CameraFrame(ReconstructionContract):
    video_id: str
    shot_id: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    world_frame: str
    intrinsic: list[Vec3]
    world_from_camera: list[Annotated[list[FiniteFloat], Field(min_length=4, max_length=4)]]
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    source: str
    origin: Literal["estimated", "synthetic"]
    metric_scale_valid: Literal[False] = False

    @model_validator(mode="after")
    def camera(self):
        k, t = np.asarray(self.intrinsic), np.asarray(self.world_from_camera)
        if k.shape != (3, 3) or k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1]):
            raise ValueError("invalid pinhole intrinsic")
        if t.shape != (4, 4) or not np.allclose(t[3], [0, 0, 0, 1]):
            raise ValueError("invalid homogeneous camera transform")
        if not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-4) or np.linalg.det(t[:3, :3]) < .999:
            raise ValueError("camera transform must be SE(3)")
        return self


class PoseFrame(ReconstructionContract):
    video_id: str
    shot_id: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    entity_id: str
    track_id: str
    world_frame: str
    pose: Pose3D | None = None
    points_world: list[Vec3] = Field(default_factory=list)
    keypoint_names: list[str] = Field(default_factory=list)
    keypoints_world: list[Vec3] = Field(default_factory=list)
    linear_velocity: Vec3 | None = None
    angular_velocity: Vec3 | None = None
    projected_centroid: Vec2 | None = None
    reprojection_error_px: Time | None = None
    origin: Literal["estimated", "synthetic", "missing"]
    representation: Literal["surface_centroid", "wrist", "point_tracks", "missing"]
    orientation_status: Literal["unknown", "pca_hypothesis", "synthetic"] = "unknown"
    source: str
    alignment_id: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def observation(self):
        if (self.pose is None) != (self.origin == "missing"):
            raise ValueError("missing poses must be explicit and contain no estimated pose")
        if self.pose is None and (self.points_world or self.keypoints_world):
            raise ValueError("missing pose cannot claim geometry")
        if len(self.keypoint_names) != len(self.keypoints_world):
            raise ValueError("keypoint names and coordinates must align")
        return self


class RelativeFrame(ReconstructionContract):
    shot_id: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    world_frame: str
    hand_id: str
    object_id: str
    hand_track_id: str
    object_track_id: str
    hand_in_object: Pose3D | None = None
    relative_position_world_xyz: Vec3 | None = None
    object_delta: Pose3D | None = None
    origin: Literal["estimated", "synthetic", "missing"]
    warnings: list[str] = Field(default_factory=list)


class ContactFrame(ReconstructionContract):
    shot_id: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    hand_id: str
    object_id: str
    hand_track_id: str | None = None
    object_track_id: str | None = None
    state: Literal["CONTACT", "NO_CONTACT", "CANDIDATE", "UNKNOWN"]
    probability: Confidence | None = None
    probability_calibrated: Literal[False] = False
    distance_2d_px: Time | None = None
    distance_3d_relative: Time | None = None
    geometry_age_s: Time | None = None
    geometry_origin: Literal["sampled", "held", "missing"] = "missing"
    motion_coupling: Confidence | None = None
    semantic_prior: Confidence | None = None
    contact_points_object: list[Vec3] = Field(default_factory=list)
    evidence_origin: Literal["estimated", "synthetic", "missing"]
    warnings: list[str] = Field(default_factory=list)


class InteractionEvent(ReconstructionContract):
    event_id: str
    shot_id: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    hand_id: str
    object_id: str
    kind: Literal["contact_on", "contact_off", "grasp_candidate", "release_candidate"]
    confidence: Confidence | None = None
    validated_grasp: Literal[False] = False
    reasons: list[str]


class RefinedAction(ReconstructionContract):
    action_id: str
    primitive: Primitive
    semantic_start_s: Time
    semantic_end_s: Time
    refined_start_s: Time | None = None
    refined_end_s: Time | None = None
    timing_source: Literal["semantic", "contact_candidate"] = "semantic"
    evidence_event_ids: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)


class AffordancePatch(ReconstructionContract):
    object_id: str
    hand_id: str
    shot_id: str
    frame_index: int = Field(ge=0)
    primitive: Literal["contact"] = "contact"
    part_name: str | None = None
    contact_patch_object_xyz: list[Vec3]
    approach_direction: Vec3 | None = None
    observed_grasp: Literal[False] = False
    source: Literal["estimated_surface_proximity", "synthetic"]


class ReconstructionReport(ReconstructionContract):
    source_run_id: str
    backend: str
    inference_mode: Literal["fixture", "live"]
    scale_mode: Literal["relative"] = "relative"
    metric_scale_valid: Literal[False] = False
    world_frames: list[str]
    sampled_frames: list[int]
    camera_frames: int
    hand_pose_frames: int
    object_pose_frames: int
    relative_pose_frames: int
    contact_frames: int = 0
    contact_events: int = 0
    reprojection_median_px: Time | None = None
    reprojection_metric: str = "mask surface centroid versus 2D mask centroid; not independent 3D ground truth"
    review_reasons: list[str]
    physical_feasibility: Literal["not_evaluated"] = "not_evaluated"


class LayerTwoHandoff(ReconstructionContract):
    video_id: str
    run_id: str
    source_run_id: str
    inference_mode: Literal["fixture", "live"]
    artifacts: dict[str, str]
    ready_for_robotization: bool
    metric_scale_valid: Literal[False] = False
    scale_mode: Literal["relative"] = "relative"
    certification: Literal["interaction_hypotheses_only"] = "interaction_hypotheses_only"
    review_reasons: list[str]
    coordinates: str = "OpenCV camera x right y down z forward; shot-local world; quaternion xyzw; T_target_source"


class GeometryWindow(ReconstructionContract):
    total: int
    offset: int
    cameras: list[CameraFrame] = Field(default_factory=list)
    hands: list[PoseFrame] = Field(default_factory=list)
    objects: list[PoseFrame] = Field(default_factory=list)
    relative: list[RelativeFrame] = Field(default_factory=list)
    contacts: list[ContactFrame] = Field(default_factory=list)


class InteractionPose(ReconstructionContract):
    entity_id: str
    track_id: str
    pose: Pose3D | None
    origin: Literal["estimated", "synthetic", "missing"]
    representation: str


class InteractionFrame(ReconstructionContract):
    shot_id: str
    world_frame: str
    frame_index: int = Field(ge=0)
    timestamp: Time
    camera_frame_index: int | None = None
    hands: list[InteractionPose]
    objects: list[InteractionPose]
    contacts: list[ContactFrame]
    current_action_ids: list[str]


class InteractionTrajectory(ReconstructionContract):
    video_id: str
    run_id: str
    source_run_id: str
    task: str
    canonical_skill: str
    entities: list[Entity]
    action_graph: ActionGraph
    refined_actions: list[RefinedAction]
    frames: list[InteractionFrame]
    scale_mode: Literal["relative"] = "relative"
    metric_scale_valid: Literal[False] = False
    quality: ReconstructionReport

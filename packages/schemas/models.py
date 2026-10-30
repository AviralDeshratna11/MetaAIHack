from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

VERSION = "0.1.0"
Confidence = Annotated[FiniteFloat, Field(ge=0, le=1)]
Time = Annotated[FiniteFloat, Field(ge=0)]
Vec2 = Annotated[list[FiniteFloat], Field(min_length=2, max_length=2)]
BBox = Annotated[list[FiniteFloat], Field(min_length=4, max_length=4)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["0.1.0"] = VERSION


class Primitive(str, Enum):
    REACH = "REACH"
    GRASP = "GRASP"
    LIFT = "LIFT"
    TRANSPORT = "TRANSPORT"
    ROTATE = "ROTATE"
    POUR = "POUR"
    INSERT = "INSERT"
    PUSH = "PUSH"
    PULL = "PULL"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    PLACE = "PLACE"
    RELEASE = "RELEASE"
    WIPE = "WIPE"
    PRESS = "PRESS"
    UNKNOWN = "UNKNOWN"


class Interval(Contract):
    start_s: Time
    end_s: Time

    @model_validator(mode="after")
    def ordered(self):
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self


class Entity(Contract):
    entity_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    category: str = Field(min_length=1)
    semantic_name: str = Field(min_length=1)
    sam_prompt: str = Field(min_length=1, max_length=100)
    role: Literal["actor", "manipulated_object", "target", "support", "other"]
    motion: Literal["manipulated", "static", "unknown"]
    handedness: Literal["left", "right", "unknown"] = "unknown"
    visibility_intervals: list[Interval] = Field(default_factory=list)
    confidence: Confidence | None = None
    uncertainty_reasons: list[str] = Field(default_factory=list)


class Predicate(Contract):
    relation: str
    entity_ids: list[str]
    negated: bool = False


class ActionSegment(Interval):
    action_id: str
    primitive: Primitive
    actor: str | None = None
    object: str | None = None
    target: str | None = None
    part: str | None = None
    timing_source: Literal["semantic"] = "semantic"
    requires_contact: bool | None = None
    preconditions: list[Predicate] = Field(default_factory=list)
    effects: list[Predicate] = Field(default_factory=list)
    confidence: Confidence | None = None
    uncertainty_reasons: list[str] = Field(default_factory=list)


class Edge(Contract):
    source: str
    target: str
    reason: Literal["precondition", "temporal", "task_dependency"]


class ActionGraph(Contract):
    nodes: list[str]
    edges: list[Edge]

    @model_validator(mode="after")
    def dag(self):
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("duplicate graph nodes")
        graph = {node: [] for node in self.nodes}
        for edge in self.edges:
            if edge.source not in graph or edge.target not in graph:
                raise ValueError("edge refers to undeclared action")
            graph[edge.source].append(edge.target)
        colors = {}

        def visit(node):
            if colors.get(node) == 1:
                raise ValueError("cyclic action graph")
            if colors.get(node) == 2:
                return
            colors[node] = 1
            for child in graph[node]:
                visit(child)
            colors[node] = 2

        for node in graph:
            visit(node)
        return self


class SemanticPlan(Contract):
    task: str = Field(min_length=1)
    canonical_skill: str = Field(min_length=1)
    duration_s: Annotated[FiniteFloat, Field(gt=0)]
    entities: list[Entity] = Field(min_length=1)
    actions: list[ActionSegment] = Field(min_length=1)
    action_graph: ActionGraph
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        ids = {e.entity_id for e in self.entities}
        if len(ids) != len(self.entities):
            raise ValueError("duplicate entity IDs")
        action_ids = [a.action_id for a in self.actions]
        if len(set(action_ids)) != len(action_ids) or set(action_ids) != set(self.action_graph.nodes):
            raise ValueError("graph nodes must equal unique action IDs")
        for entity in self.entities:
            if any(i.end_s > self.duration_s for i in entity.visibility_intervals):
                raise ValueError("visibility outside duration")
        for action in self.actions:
            if action.end_s > self.duration_s:
                raise ValueError("action outside duration")
            refs = [action.actor, action.object, action.target]
            refs += [ref for p in action.preconditions + action.effects for ref in p.entity_ids]
            if any(ref is not None and ref not in ids for ref in refs):
                raise ValueError("undeclared entity reference")
        return self


class Shot(Contract):
    shot_id: str
    start_frame: Annotated[int, Field(ge=0)]
    end_frame: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def order(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("shot frame range is half-open and nonempty")
        return self


class Provenance(Contract):
    source_uri: str | None = None
    rights_status: Literal["team_recorded", "licensed", "user_supplied", "synthetic", "unknown"]
    license: str | None = None
    consent: str | None = None
    uploader: str | None = None


class VideoAsset(Contract):
    video_id: str
    original_ref: str
    source_hash: str
    byte_count: int
    provenance: Provenance


class VideoManifest(Contract):
    video_id: str
    original: dict
    normalized_ref: str
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    fps_num: Annotated[int, Field(gt=0)]
    fps_den: Annotated[int, Field(gt=0)] = 1
    frame_count: Annotated[int, Field(gt=0)]
    duration_s: Time
    pixel_format: str = "yuv420p"
    normalization_hash: str
    frame_map_ref: str
    shots: list[Shot]
    keyframe_refs: list[str]
    diagnostics: dict


class TrackFrame(Contract):
    video_id: str
    shot_id: str
    frame_index: Annotated[int, Field(ge=0)]
    timestamp: Time
    source_timestamp: FiniteFloat
    entity_id: str
    track_id: str
    provider_track_id: str | None = None
    mask_ref: str | None = None
    bbox_xyxy: BBox | None = None
    centroid: Vec2 | None = None
    centroid_normalized: Vec2 | None = None
    provider_confidence: Confidence | None = None
    tracking_confidence: Confidence | None = None
    observed: bool
    visibility: Literal["VISIBLE", "PARTIALLY_OCCLUDED", "FULLY_OCCLUDED", "CANDIDATE_REAPPEARANCE", "LOST"]
    origin: Literal["measured", "interpolated", "predicted", "missing"]
    identity_status: Literal["associated", "ambiguous", "unverified", "lost"]
    warnings: list[str] = Field(default_factory=list)
    model_run_id: str

    @model_validator(mode="after")
    def observation(self):
        if self.observed and (self.mask_ref is None or self.bbox_xyxy is None or self.origin != "measured"):
            raise ValueError("observed frame requires measured mask and bbox")
        if not self.observed and self.mask_ref is not None:
            raise ValueError("missing observation cannot claim a measured mask")
        if self.bbox_xyxy is not None:
            x1, y1, x2, y2 = self.bbox_xyxy
            if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("invalid half-open bbox")
        return self


class TrackSummary(Contract):
    entity_id: str
    track_id: str
    observed_frame_coverage: Confidence
    expected_visible_frame_coverage: Confidence | None = None
    missing_frames: int
    longest_missing_run: int
    reinitializations: int
    verified_id_switches: int | None = None
    anomaly_count: int
    identity_status: str


class ArtifactManifest(Contract):
    artifact_id: str
    uri: str
    sha256: str
    byte_count: int
    media_type: str
    stage: str
    run_id: str
    input_hashes: list[str]
    config_hash: str
    code_hash: str
    model: str | None = None
    model_revision: str | None = None
    prompt_hash: str | None = None
    created_at: datetime
    inference_mode: Literal["fixture", "live"]


class ModelRun(Contract):
    model_run_id: str
    model: str
    revision: str | None = None
    stage: str
    inference_mode: Literal["fixture", "live"]
    input_hash: str
    config_hash: str
    prompt_hash: str
    status: str
    request_id: str | None = None
    latency_ms: int | None = None
    usage: dict = Field(default_factory=dict)
    actual_cost_usd: FiniteFloat | None = None
    estimated_cost_usd: FiniteFloat | None = None
    attempt: int = 1
    warnings: list[str] = Field(default_factory=list)
    error: dict | None = None


class StageResult(Contract):
    stage: str
    run_id: str
    status: str
    artifact_ids: list[str]
    warnings: list[str]
    error: dict | None = None


class JobEvent(Contract):
    sequence: int
    job_id: str
    status: str
    stage: str | None
    created_at: datetime
    detail: dict = Field(default_factory=dict)


class LayerOneHandoffManifest(Contract):
    video_id: str
    run_id: str
    inference_mode: Literal["fixture", "live"]
    artifacts: dict[str, str]
    entities: list[str]
    ready_for_geometry: bool
    review_reasons: list[str]
    metric_scale_valid: Literal[False] = False
    coordinates: Literal["normalized-video pixels; x right, y down; half-open boxes; zero-based frames; seconds from normalized start"] = "normalized-video pixels; x right, y down; half-open boxes; zero-based frames; seconds from normalized start"
    certification: Literal["2d_perception_only"] = "2d_perception_only"


class UploadRequest(Contract):
    filename: str = Field(min_length=1, max_length=255)
    byte_count: Annotated[int, Field(gt=0)]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: Provenance


class ProcessRequest(Contract):
    idempotency_key: str = Field(min_length=1, max_length=200)


class Correction(Contract):
    source_job_id: str
    entity_id: str
    shot_id: str
    frame_index: Annotated[int, Field(ge=0)]
    kind: Literal["point", "box", "association"]
    point: Vec2 | None = None
    bbox_xyxy: BBox | None = None
    provider_track_id: str | None = None

    @model_validator(mode="after")
    def payload(self):
        if self.kind == "point" and self.point is None:
            raise ValueError("point correction requires point")
        if self.kind == "box" and self.bbox_xyxy is None:
            raise ValueError("box correction requires bbox")
        if self.kind == "association" and self.provider_track_id is None:
            raise ValueError("association requires provider track ID")
        if self.bbox_xyxy:
            x1, y1, x2, y2 = self.bbox_xyxy
            if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("invalid correction box")
        return self


class ErrorResponse(Contract):
    code: str
    message: str
    retryable: bool


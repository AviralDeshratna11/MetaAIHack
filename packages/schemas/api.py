from datetime import datetime
from typing import Literal

from pydantic import Field

from packages.schemas.models import (ArtifactManifest, Contract, ModelRun, Provenance, SemanticPlan,
                                    TrackFrame, TrackSummary)


class HealthResponse(Contract):
    status: Literal["ok", "ready"]
    inference_mode: Literal["fixture", "live"]
    scope: str | None = None


class UploadResponse(Contract):
    video_id: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_in: int
    inference_mode: Literal["fixture", "live"]


class UploadCompleteResponse(Contract):
    video_id: str
    status: str
    probe: dict | None = None


class JobView(Contract):
    job_id: str
    video_id: str
    run_id: str
    status: str
    stage: str | None
    inference_mode: Literal["fixture", "live"]
    error: dict | None = None
    source_job_id: str | None = None
    created_at: datetime


class StageView(Contract):
    stage: str
    attempt: int
    status: str
    error: dict | None


class ModelRunView(ModelRun):
    raw_ref: str | None = None


class JobDetail(JobView):
    stages: list[StageView]
    model_runs: list[ModelRunView]


class VideoListItem(Contract):
    video_id: str
    filename: str
    status: str


class VideoListResponse(Contract):
    videos: list[VideoListItem]


class VideoDetail(VideoListItem):
    provenance: Provenance
    probe: dict | None
    jobs: list[JobView]
    source_url: str | None


class ArtifactView(ArtifactManifest):
    name: str
    url: str


class ArtifactsResponse(Contract):
    run_id: str
    inference_mode: Literal["fixture", "live"]
    artifacts: list[ArtifactView]


class RLEMask(Contract):
    encoding: Literal["row-major-rle-v1"]
    height: int = Field(gt=0)
    width: int = Field(gt=0)
    counts: list[int]


class TracksResponse(Contract):
    total: int
    offset: int
    tracks: list[TrackFrame]
    masks: dict[str, RLEMask]


class Anchor(Contract):
    entity_id: str
    shot_id: str
    frame_index: int
    mask_ref: str
    method: str


class TrackingReport(Contract):
    inference_mode: Literal["fixture", "live"]
    calibration: str
    summaries: list[TrackSummary]
    anchors: list[Anchor]
    review_reasons: list[str]
    mask_bundles: list[str]
    reprojection: Literal["not_evaluated"]
    physical_feasibility: Literal["not_evaluated"]

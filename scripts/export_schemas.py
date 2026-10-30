import json
import sys
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from packages.schemas.models import (ActionGraph, ArtifactManifest, Correction, Entity, ErrorResponse,
    JobEvent, LayerOneHandoffManifest, ModelRun, ProcessRequest, Provenance, SemanticPlan, StageResult,
    TrackFrame, TrackSummary, UploadRequest, VideoAsset, VideoManifest)
from packages.schemas.api import (ArtifactsResponse, HealthResponse, JobDetail, JobView, TrackingReport,
    TracksResponse, UploadCompleteResponse, UploadResponse, VideoDetail, VideoListResponse)


def main():
    types = Union[ActionGraph, ArtifactManifest, Correction, Entity, ErrorResponse, JobEvent,
        LayerOneHandoffManifest, ModelRun, ProcessRequest, Provenance, SemanticPlan, StageResult,
        TrackFrame, TrackSummary, UploadRequest, VideoAsset, VideoManifest, ArtifactsResponse, HealthResponse,
        JobDetail, JobView, TrackingReport, TracksResponse, UploadCompleteResponse, UploadResponse, VideoDetail, VideoListResponse]
    schema = TypeAdapter(types).json_schema()
    schema["title"] = "Video2RobotContracts"
    content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    target = Path("packages/schemas/generated/contracts.schema.json")
    if "--check" in sys.argv:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("Generated JSON Schema is stale; run python -m scripts.export_schemas")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()


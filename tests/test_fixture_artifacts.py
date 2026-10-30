import gzip
import json
from pathlib import Path

import pyarrow.parquet as pq

from packages.schemas.models import LayerOneHandoffManifest, SemanticPlan, TrackFrame
from packages.video.masks import decode_rle


def test_checked_in_fixture_contracts_and_mask_references():
    plan = SemanticPlan.model_validate_json(Path("fixtures/semantic_plan.json").read_text())
    handoff = LayerOneHandoffManifest.model_validate_json(Path("fixtures/handoff_manifest.json").read_text())
    assert handoff.inference_mode == "fixture" and not handoff.ready_for_geometry
    rows = pq.read_table("fixtures/tracks.parquet").to_pylist()
    assert len(rows) == 540 and len(plan.entities) == 3
    bundles = {}
    for raw in rows:
        row = TrackFrame.model_validate(raw)
        if row.mask_ref:
            path, fragment = row.mask_ref.split("#")
            if path not in bundles:
                bundles[path] = json.loads(gzip.decompress(Path(path).read_bytes()))
            mask = decode_rle(bundles[path][fragment])
            assert mask.shape == (360, 640)

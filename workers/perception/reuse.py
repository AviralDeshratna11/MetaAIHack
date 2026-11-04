"""Re-associate stored masks without new hosted calls or provider-ID changes."""
import json
import tempfile
from pathlib import Path
import pyarrow.parquet as pq
from packages.schemas.models import SemanticPlan, VideoManifest
from workers.geometry.reconstruct import MaskReader


class StoredTrackingProvider:
    def __init__(self, artifacts, store, mode):
        self.mode = mode
        refs = {a.name:a.manifest['uri'] for a in artifacts}
        self.manifest = VideoManifest.model_validate_json(store.read(refs['manifest.json']))
        self.plan = SemanticPlan.model_validate_json(store.read(refs['semantic_plan.json']))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'tracks.parquet'; store.download(refs['tracks.parquet'],path)
            self.rows = pq.read_table(path).to_pylist()
        self.masks = MaskReader(store.read)
        self.calls = 0

    def track(self, video, prompt, width, height, corrections, record):
        # tracking() invokes one request per semantic entity per shot, in order.
        shot = self.manifest.shots[self.calls//len(self.plan.entities)]
        entity = self.plan.entities[self.calls%len(self.plan.entities)]
        self.calls += 1
        records = []
        for row in self.rows:
            if row['entity_id'] != entity.entity_id or row['shot_id'] != shot.shot_id or not row['observed']: continue
            record.last_id = row['model_run_id']
            records.append({'frame':row['frame_index']-shot.start_frame,'object_id':row['provider_track_id'],
                'mask':self.masks(row['mask_ref']),'confidence':row['provider_confidence']})
        return records

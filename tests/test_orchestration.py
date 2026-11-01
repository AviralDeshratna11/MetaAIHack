import time

import pytest
from sqlalchemy import select

from apps.api.orchestration import claim, heartbeat, reconcile, schedule
from packages.common.utils import DomainError
from workers.pipeline import all_corrections, stage_start


def seed(db):
    with db.transaction() as s:
        video = db.Video(id="video", filename="test.mp4", byte_count=1, sha256="0" * 64,
                         source_key="source", provenance={})
        s.add(video); s.flush()
        job = schedule(s, video, "unique", {"inference_mode": "fixture"})
    return job


def test_processing_is_idempotent_and_transaction_creates_outbox(database):
    db = database; first = seed(db)
    with db.transaction() as s:
        second = schedule(s, s.get(db.Video, "video"), "unique", {"inference_mode": "fixture"})
        assert second.id == first.id
        assert len(s.scalars(select(db.Outbox)).all()) == 1


def test_duplicate_queue_delivery_cannot_claim_active_job(database):
    job = seed(database)
    token = claim(job.id)
    assert token and claim(job.id) is None and heartbeat(job.id, token)


def test_expired_lease_is_requeued_and_fenced(database):
    db = database; job = seed(db); old_token = claim(job.id)
    with db.transaction() as s:
        s.get(db.Job, job.id).lease_until = time.time() - 1
    reconcile()
    new_token = claim(job.id)
    assert new_token and new_token != old_token
    assert not heartbeat(job.id, old_token)


def test_cancel_revokes_stage_publication(database):
    db = database; job = seed(db); token = claim(job.id)
    with db.transaction() as s:
        s.get(db.Job, job.id).cancel_requested = True
    with pytest.raises(DomainError): stage_start(job.id, token, "tracking", "hash")


def test_completed_stage_resumes_and_config_hash_invalidates_cache(database):
    db = database; job = seed(db); token = claim(job.id)
    stage, cached = stage_start(job.id, token, "preprocessing", "hash-a")
    assert not cached
    with db.transaction() as s:
        row = s.get(db.StageRun, stage.id); row.status = "COMPLETED"; row.result = {"artifact": "key"}
    resumed, cached = stage_start(job.id, token, "preprocessing", "hash-a")
    assert cached and resumed.result["artifact"] == "key"
    with db.transaction() as s:
        other = schedule(s, s.get(db.Video, "video"), "other", {"inference_mode": "fixture"})
    token2 = claim(other.id)
    changed, cached = stage_start(other.id, token2, "preprocessing", "hash-b")
    assert not cached


def test_stage_recovery_has_bounded_attempts(database):
    db = database; job = seed(db); token = claim(job.id)
    for _ in range(3): stage_start(job.id, token, "tracking", "same")
    with pytest.raises(DomainError) as exc: stage_start(job.id, token, "tracking", "same")
    assert exc.value.code == "E_STAGE_RETRIES"


def test_visual_correction_keeps_other_anchors_and_invalidates_old_provider_association(database):
    db = database
    job = seed(db)
    corrections = [
        {"entity_id": "mug", "shot_id": "shot_000", "kind": "association", "frame_index": 0, "provider_track_id": "2"},
        {"entity_id": "mug", "shot_id": "shot_000", "kind": "point", "frame_index": 1, "point": [4., 5.]},
        {"entity_id": "mug", "shot_id": "shot_000", "kind": "point", "frame_index": 7, "point": [7., 5.]},
    ]
    with db.transaction() as s:
        for i, correction in enumerate(corrections):
            child = schedule(s, s.get(db.Video, "video"), f"correction-{i}", job.config, job.id)
            s.add(db.CorrectionRecord(video_id="video", job_id=child.id, data=correction))
            job = child
    effective = all_corrections(job)
    assert effective == corrections[1:]

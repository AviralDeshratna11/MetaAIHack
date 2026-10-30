import time

from redis import Redis
from rq import Queue
from sqlalchemy import select, update

from apps.api.db import Event, Job, Outbox, transaction
from packages.common.config import settings
from packages.common.utils import DomainError, uid

TERMINAL = {"COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"}


def emit(session, job, detail=None):
    session.add(Event(job_id=job.id, status=job.status, stage=job.stage,
                      created_at=time.time(), detail=detail or {}))


def schedule(session, video, key, config, source_job_id=None):
    existing = session.scalar(select(Job).where(Job.video_id == video.id, Job.idempotency_key == key))
    if existing:
        return existing
    job = Job(video_id=video.id, idempotency_key=key, mode=config["inference_mode"],
              config=config, created_at=time.time(), source_job_id=source_job_id)
    session.add(job)
    session.flush()
    emit(session, job)
    session.add(Outbox(job_id=job.id))
    return job


def claim(job_id):
    token = uid("lease")
    with transaction() as s:
        result = s.execute(update(Job).where(Job.id == job_id, Job.cancel_requested.is_(False),
            Job.status.not_in(TERMINAL), (Job.lease_until.is_(None) | (Job.lease_until < time.time())))
            .values(lease_token=token, lease_until=time.time() + 90))
        return token if result.rowcount else None


def heartbeat(job_id, token):
    with transaction() as s:
        result = s.execute(update(Job).where(Job.id == job_id, Job.lease_token == token,
            Job.cancel_requested.is_(False)).values(lease_until=time.time() + 90))
        return bool(result.rowcount)


def assert_owner(s, job_id, token):
    job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job.cancel_requested or job.lease_token != token:
        raise DomainError("E_CANCELLED", "Job cancelled or worker lease lost", 409)
    return job


def dispatch_once():
    queue = Queue("video2robot", connection=Redis.from_url(settings().redis_url))
    with transaction() as s:
        rows = s.scalars(select(Outbox).where(Outbox.sent_at.is_(None)).with_for_update(skip_locked=True)).all()
        for row in rows:
            queue.enqueue("workers.pipeline.run_job", row.job_id, job_id=row.id,
                          job_timeout=settings().stage_timeout_seconds * 4, result_ttl=86400)
            row.sent_at = time.time()


def reconcile():
    with transaction() as s:
        jobs = s.scalars(select(Job).where(Job.status.not_in(TERMINAL)).with_for_update(skip_locked=True)).all()
        for job in jobs:
            if job.cancel_requested:
                job.status = "CANCELLED"
                job.lease_token = None
                emit(s, job)
            elif job.lease_until is not None and job.lease_until < time.time():
                job.lease_until = None
                job.lease_token = None
                s.add(Outbox(job_id=job.id))
                emit(s, job, {"recovery": "expired worker lease"})
            elif job.lease_until is None:
                # Recover a queue flush or crash after enqueue, with a bounded redelivery interval.
                latest = s.scalar(select(Outbox).where(Outbox.job_id == job.id).order_by(Outbox.sent_at.desc()))
                if latest is None or (latest.sent_at is not None and latest.sent_at < time.time() - 120):
                    s.add(Outbox(job_id=job.id))


def main():
    while True:
        try:
            reconcile()
            dispatch_once()
        except Exception as exc:
            print(f"dispatcher: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()


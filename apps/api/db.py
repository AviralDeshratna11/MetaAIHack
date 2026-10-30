from contextlib import contextmanager

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from packages.common.config import settings
from packages.common.utils import uid


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uid("vid"))
    filename: Mapped[str] = mapped_column(String)
    byte_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="PENDING_UPLOAD")
    provenance: Mapped[dict] = mapped_column(JSON)
    probe: Mapped[dict | None] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (UniqueConstraint("video_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uid("job"))
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, default=lambda: uid("run"))
    idempotency_key: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    stage: Mapped[str | None] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSON)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_token: Mapped[str | None] = mapped_column(String)
    lease_until: Mapped[float | None] = mapped_column(Float)
    error: Mapped[dict | None] = mapped_column(JSON)
    source_job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id"))
    created_at: Mapped[float] = mapped_column(Float)


class StageRun(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (UniqueConstraint("job_id", "stage", "attempt"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uid("stage"))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(Integer)
    cache_key: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    stage_run_id: Mapped[str] = mapped_column(ForeignKey("stage_runs.id"))
    name: Mapped[str] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSON)


class ModelExecution(Base):
    __tablename__ = "model_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class EntityRecord(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("job_id", "entity_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"))
    entity_id: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


class ActionRecord(Base):
    __tablename__ = "action_segments"
    __table_args__ = (UniqueConstraint("job_id", "action_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"))
    action_id: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


class CorrectionRecord(Base):
    __tablename__ = "corrections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uid("cor"))
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "job_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String)
    stage: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
    detail: Mapped[dict] = mapped_column(JSON)


class Outbox(Base):
    __tablename__ = "dispatch_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uid("dispatch"))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    sent_at: Mapped[float | None] = mapped_column(Float)


engine = create_engine(settings().database_url, pool_pre_ping=True)
if settings().database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with Session.begin() as session:
        yield session


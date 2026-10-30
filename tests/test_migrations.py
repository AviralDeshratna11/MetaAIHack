import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_frozen_migration_roundtrip(tmp_path, monkeypatch):
    from apps.api import db
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    monkeypatch.setattr(db, "engine", engine)
    cfg = Config("apps/api/alembic.ini")
    command.upgrade(cfg, "head")
    assert set(db.Base.metadata.tables).issubset(inspect(engine).get_table_names())
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

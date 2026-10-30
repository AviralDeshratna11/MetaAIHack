import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def database():
    from apps.api import db
    original = db.Session.kw["bind"]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    db.Session.configure(bind=engine)
    yield db
    db.Session.configure(bind=original)
    engine.dispose()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_INTEGRATION") != "1":
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Set RUN_INTEGRATION=1 with running Docker dependencies"))

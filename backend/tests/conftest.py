import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.models import Base  # noqa: E402


# The models target Postgres. Teaching SQLite to render the two dialect-specific
# types keeps the schema definition untouched while letting tests exercise real
# query semantics — session scoping, bulk updates — instead of asserting that a
# mock received a call.
@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw) -> str:
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_on_sqlite(type_, compiler, **kw) -> str:
    return "VARCHAR(36)"


@pytest.fixture
def db_session():
    """In-memory SQLite session with the full schema, torn down per test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _study_guard_off_by_default(monkeypatch):
    """The active-study guard reads a nightly-written file; keep it opt-in in tests.

    The hv_dip engine force-reviews candidates when a weak-pattern study fired.
    Tests that do not exercise this feature must not be affected by whatever
    ``.cache/fiidesk/study_guard.json`` happens to contain on disk.
    """
    monkeypatch.setattr(
        "app.services.hv_dip.engine.hv_dip_force_review",
        lambda: (False, None),
    )

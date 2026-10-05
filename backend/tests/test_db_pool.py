"""SQLAlchemy pool: pre_ping + recycle (no pool_size change)."""

from app.db import engine, engine_kwargs


def test_engine_kwargs_pre_ping_and_recycle():
    kw = engine_kwargs()
    assert kw["pool_pre_ping"] is True
    assert kw["pool_recycle"] == 1800
    assert "pool_size" not in kw


def test_db_engine_imports():
    assert engine is not None
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 1800

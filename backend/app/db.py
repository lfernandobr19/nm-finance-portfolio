from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def engine_kwargs() -> dict:
    settings = get_settings()
    return {
        "pool_pre_ping": True,
        "pool_recycle": int(settings.db_pool_recycle_seconds),
    }


settings = get_settings()
engine = create_engine(settings.database_url, **engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

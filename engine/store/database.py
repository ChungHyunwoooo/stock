from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.store.models import Base

_engine: Engine | None = None


def get_engine(db_url: str = "sqlite:///tse.db") -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(db_url, echo=False)
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(db_url: str = "sqlite:///tse.db") -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)

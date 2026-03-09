from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from engine.store.database import get_session


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    with get_session() as session:
        yield session

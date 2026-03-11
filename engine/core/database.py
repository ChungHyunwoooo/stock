
from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import Base

logger = logging.getLogger(__name__)

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

def _migrate_backtests_phase2(engine: Engine) -> None:
    """Add Phase 2 columns to backtests table if missing.

    Uses PRAGMA table_info to detect existing columns, then
    ALTER TABLE ADD COLUMN for each missing one.  Idempotent.
    """
    with engine.connect() as conn:
        result = conn.execute(sa.text("PRAGMA table_info(backtests)"))
        existing = {row[1] for row in result}

        new_columns = {
            "slippage_model": "VARCHAR(50) DEFAULT 'none'",
            "fee_rate": "REAL DEFAULT 0.0",
            "wf_result": "VARCHAR(10)",
            "cpcv_mode": "BOOLEAN DEFAULT 0",
            "multi_symbol_result": "TEXT",
        }

        for col_name, col_type in new_columns.items():
            if col_name not in existing:
                conn.execute(
                    sa.text(f"ALTER TABLE backtests ADD COLUMN {col_name} {col_type}")
                )
                logger.info("Migration: added column backtests.%s", col_name)
        conn.commit()


def init_db(db_url: str = "sqlite:///tse.db") -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    _migrate_backtests_phase2(engine)

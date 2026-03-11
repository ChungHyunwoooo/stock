"""PaperBroker DB persistence tests (Phase 3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import Base, PaperBalance, PaperPnlSnapshot


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def db_session(tmp_path: Path):
    """In-memory SQLite session for isolation."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def db_engine(tmp_path: Path):
    """File-based SQLite engine for migration tests."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


# ── Task 1: DB Models ────────────────────────────────────────


class TestPaperBalance:
    def test_save_load_roundtrip(self, db_session: Session):
        record = PaperBalance(
            strategy_id="test_strat",
            balance=10_000_000.0,
            equity=10_000_000.0,
            unrealized_pnl=0.0,
            snapshot_at=datetime.now(timezone.utc),
        )
        db_session.add(record)
        db_session.flush()

        loaded = db_session.get(PaperBalance, record.id)
        assert loaded is not None
        assert loaded.strategy_id == "test_strat"
        assert loaded.balance == 10_000_000.0
        assert loaded.equity == 10_000_000.0
        assert loaded.unrealized_pnl == 0.0

    def test_default_unrealized_pnl(self, db_session: Session):
        record = PaperBalance(
            strategy_id="s1",
            balance=100.0,
            equity=100.0,
            snapshot_at=datetime.now(timezone.utc),
        )
        db_session.add(record)
        db_session.flush()
        assert record.unrealized_pnl == 0.0


class TestPaperPnlSnapshot:
    def test_save_load_roundtrip(self, db_session: Session):
        record = PaperPnlSnapshot(
            strategy_id="test_strat",
            date="2026-03-11",
            cumulative_pnl=5000.0,
            daily_pnl=1000.0,
            trade_count=10,
            win_count=6,
            equity=10_005_000.0,
        )
        db_session.add(record)
        db_session.flush()

        loaded = db_session.get(PaperPnlSnapshot, record.id)
        assert loaded is not None
        assert loaded.strategy_id == "test_strat"
        assert loaded.date == "2026-03-11"
        assert loaded.cumulative_pnl == 5000.0
        assert loaded.trade_count == 10
        assert loaded.win_count == 6

    def test_unique_constraint_strategy_date(self, db_session: Session):
        """Same (strategy_id, date) should violate unique constraint."""
        r1 = PaperPnlSnapshot(
            strategy_id="s1", date="2026-03-11",
            cumulative_pnl=100.0, daily_pnl=100.0, equity=10100.0,
        )
        db_session.add(r1)
        db_session.flush()

        r2 = PaperPnlSnapshot(
            strategy_id="s1", date="2026-03-11",
            cumulative_pnl=200.0, daily_pnl=200.0, equity=10200.0,
        )
        db_session.add(r2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.flush()


# ── Task 1: Migration ────────────────────────────────────────


class TestMigration:
    def test_migrate_paper_phase3_creates_tables(self, db_engine):
        from engine.core.database import _migrate_paper_phase3

        _migrate_paper_phase3(db_engine)

        import sqlalchemy as sa
        with db_engine.connect() as conn:
            # Check paper_balances exists
            result = conn.execute(sa.text("PRAGMA table_info(paper_balances)"))
            cols = {row[1] for row in result}
            assert "strategy_id" in cols
            assert "balance" in cols
            assert "equity" in cols

            # Check paper_pnl_snapshots exists
            result = conn.execute(sa.text("PRAGMA table_info(paper_pnl_snapshots)"))
            cols = {row[1] for row in result}
            assert "strategy_id" in cols
            assert "date" in cols
            assert "cumulative_pnl" in cols

    def test_migrate_paper_phase3_idempotent(self, db_engine):
        from engine.core.database import _migrate_paper_phase3

        _migrate_paper_phase3(db_engine)
        _migrate_paper_phase3(db_engine)  # Should not raise


# ── Task 1: PaperRepository ──────────────────────────────────


class TestPaperRepository:
    def test_save_balance(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        record = PaperBalance(
            strategy_id="s1",
            balance=10_000.0,
            equity=10_000.0,
            snapshot_at=datetime.now(timezone.utc),
        )
        saved = repo.save_balance(db_session, record)
        assert saved.id is not None

    def test_get_latest_balance(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        now = datetime.now(timezone.utc)

        # Save two balances for same strategy
        r1 = PaperBalance(
            strategy_id="s1", balance=10_000.0, equity=10_000.0,
            snapshot_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        )
        r2 = PaperBalance(
            strategy_id="s1", balance=9_500.0, equity=9_500.0,
            snapshot_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
        )
        repo.save_balance(db_session, r1)
        repo.save_balance(db_session, r2)

        latest = repo.get_latest_balance(db_session, "s1")
        assert latest is not None
        assert latest.balance == 9_500.0

    def test_get_latest_balance_none(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        assert repo.get_latest_balance(db_session, "nonexistent") is None

    def test_save_daily_snapshot_upsert(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()

        snap1 = PaperPnlSnapshot(
            strategy_id="s1", date="2026-03-11",
            cumulative_pnl=100.0, daily_pnl=100.0,
            trade_count=5, win_count=3, equity=10100.0,
        )
        repo.save_daily_snapshot(db_session, snap1)

        # Upsert with new values
        snap2 = PaperPnlSnapshot(
            strategy_id="s1", date="2026-03-11",
            cumulative_pnl=200.0, daily_pnl=200.0,
            trade_count=8, win_count=5, equity=10200.0,
        )
        repo.save_daily_snapshot(db_session, snap2)

        # Should have only one record for (s1, 2026-03-11)
        snapshots = repo.get_daily_snapshots(db_session, "s1")
        assert len(snapshots) == 1
        assert snapshots[0].cumulative_pnl == 200.0
        assert snapshots[0].trade_count == 8

    def test_get_daily_snapshots_order_and_limit(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        for day in range(1, 11):
            snap = PaperPnlSnapshot(
                strategy_id="s1", date=f"2026-03-{day:02d}",
                cumulative_pnl=day * 100.0, daily_pnl=100.0,
                equity=10000.0 + day * 100.0,
            )
            repo.save_daily_snapshot(db_session, snap)

        # limit=5 should return 5 newest
        snapshots = repo.get_daily_snapshots(db_session, "s1", limit=5)
        assert len(snapshots) == 5
        assert snapshots[0].date == "2026-03-10"  # newest first

    def test_get_paper_strategies(self, db_session: Session):
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        for sid in ["strat_a", "strat_b", "strat_a"]:
            snap = PaperPnlSnapshot(
                strategy_id=sid, date=f"2026-03-11",
                cumulative_pnl=0.0, daily_pnl=0.0, equity=10000.0,
            )
            # Use upsert to avoid unique constraint violation for strat_a
            repo.save_daily_snapshot(db_session, snap)

        strategies = repo.get_paper_strategies(db_session)
        assert set(strategies) == {"strat_a", "strat_b"}


# ── Task 1: Config ────────────────────────────────────────────


class TestPaperTradingConfig:
    def test_config_file_exists(self):
        config_path = Path("config/paper_trading.json")
        assert config_path.exists(), "config/paper_trading.json must exist"

    def test_config_structure(self):
        config_path = Path("config/paper_trading.json")
        data = json.loads(config_path.read_text())

        assert "check_interval_hours" in data
        assert "promotion_gates" in data
        assert "timeframe_min_trades" in data

        gates = data["promotion_gates"]
        assert "min_days" in gates
        assert "min_sharpe" in gates
        assert "min_win_rate" in gates
        assert "max_drawdown" in gates
        assert "min_cumulative_pnl" in gates

        tf = data["timeframe_min_trades"]
        assert tf["1m"] == 20
        assert tf["1d"] == 5

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
                strategy_id=sid, date="2026-03-11",
                cumulative_pnl=0.0, daily_pnl=0.0,
                trade_count=0, win_count=0, equity=10000.0,
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


# ── Task 2: PaperBroker DB Persistence ───────────────────────


@pytest.fixture()
def paper_db(tmp_path: Path):
    """File-based SQLite for PaperBroker integration tests."""
    import engine.core.database as _db

    # Reset global engine singleton for test isolation
    if _db._engine is not None:
        _db._engine.dispose()
        _db._engine = None

    db_path = tmp_path / "paper_test.db"
    db_url = f"sqlite:///{db_path}"
    yield db_url

    # Cleanup after test
    if _db._engine is not None:
        _db._engine.dispose()
        _db._engine = None


class TestPaperBrokerInit:
    def test_strategy_id_required(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        broker = PaperBroker(strategy_id="test_strat", db_url=paper_db)
        assert broker.strategy_id == "test_strat"

    def test_initial_balance_default(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        broker = PaperBroker(strategy_id="s1", db_url=paper_db)
        bal = broker._fetch_raw_balance()
        assert bal["total_equity"] == 10_000_000

    def test_restore_balance_from_db(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        # First broker saves balance
        b1 = PaperBroker(strategy_id="s1", initial_balance=50_000, db_url=paper_db)
        b1._save_balance_snapshot()

        # Second broker restores from DB
        b2 = PaperBroker(strategy_id="s1", initial_balance=50_000, db_url=paper_db)
        bal = b2._fetch_raw_balance()
        assert bal["total_equity"] == 50_000

    def test_different_strategies_isolated(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        b1 = PaperBroker(strategy_id="s1", initial_balance=100_000, db_url=paper_db)
        b1._save_balance_snapshot()

        b2 = PaperBroker(strategy_id="s2", initial_balance=200_000, db_url=paper_db)
        b2._save_balance_snapshot()

        # Restore and verify isolation
        b1_new = PaperBroker(strategy_id="s1", initial_balance=100_000, db_url=paper_db)
        b2_new = PaperBroker(strategy_id="s2", initial_balance=200_000, db_url=paper_db)

        assert b1_new._fetch_raw_balance()["total_equity"] == 100_000
        assert b2_new._fetch_raw_balance()["total_equity"] == 200_000


class TestPaperBrokerPersistence:
    def test_save_balance_snapshot(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        broker = PaperBroker(strategy_id="s1", initial_balance=10_000, db_url=paper_db)
        broker._save_balance_snapshot()

        # Verify in DB
        from engine.core.database import get_session
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        with get_session() as session:
            latest = repo.get_latest_balance(session, "s1")
            assert latest is not None
            assert latest.balance == 10_000

    def test_save_daily_snapshot(self, paper_db: str):
        from engine.execution.paper_broker import PaperBroker

        broker = PaperBroker(strategy_id="s1", initial_balance=10_000, db_url=paper_db)
        broker.save_daily_snapshot()

        from engine.core.database import get_session
        from engine.core.repository import PaperRepository

        repo = PaperRepository()
        with get_session() as session:
            snaps = repo.get_daily_snapshots(session, "s1")
            assert len(snaps) >= 1

    def test_db_failure_does_not_block(self, paper_db: str, monkeypatch):
        """DB failure during save should not raise."""
        from engine.execution.paper_broker import PaperBroker

        broker = PaperBroker(strategy_id="s1", initial_balance=10_000, db_url=paper_db)

        # Monkeypatch to simulate DB failure
        from engine.core import repository
        original_save = repository.PaperRepository.save_balance
        def failing_save(*args, **kwargs):
            raise RuntimeError("DB down")
        monkeypatch.setattr(repository.PaperRepository, "save_balance", failing_save)

        # Should not raise
        broker._save_balance_snapshot()


class TestTradeRepositoryListOpenExtended:
    """TradeRepository.list_open needs strategy_name + broker filters for PaperBroker."""

    def test_list_open_with_strategy_and_broker(self, db_session: Session):
        from engine.core.repository import TradeRepository
        from engine.core.db_models import TradeRecord

        repo = TradeRepository()
        now = datetime.now(timezone.utc)

        # Paper trade for s1
        t1 = TradeRecord(
            trade_id="t1", strategy_name="s1", symbol="BTC", timeframe="1h",
            side="long", broker="paper", entry_price=50000, entry_quantity=1,
            entry_at=now, status="open",
        )
        # Live trade for s1
        t2 = TradeRecord(
            trade_id="t2", strategy_name="s1", symbol="ETH", timeframe="1h",
            side="long", broker="live", entry_price=3000, entry_quantity=1,
            entry_at=now, status="open",
        )
        # Paper trade for s2
        t3 = TradeRecord(
            trade_id="t3", strategy_name="s2", symbol="BTC", timeframe="1h",
            side="long", broker="paper", entry_price=50000, entry_quantity=1,
            entry_at=now, status="open",
        )
        db_session.add_all([t1, t2, t3])
        db_session.flush()

        # Filter by strategy_name and broker
        result = repo.list_open(db_session, strategy_name="s1", broker="paper")
        assert len(result) == 1
        assert result[0].trade_id == "t1"

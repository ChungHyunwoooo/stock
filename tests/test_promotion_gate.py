"""Tests for PromotionGate domain logic and LifecycleManager integration."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import Base, PaperPnlSnapshot, TradeRecord
from engine.core.repository import BacktestRepository, PaperRepository, TradeRepository
from engine.schema import StrategyDefinition, StrategyStatus
from engine.strategy.promotion_gate import (
    PromotionCheck,
    PromotionConfig,
    PromotionGate,
    PromotionResult,
    resolve_promotion_config,
)
from engine.strategy.lifecycle_manager import (
    InvalidTransitionError,
    LifecycleManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    yield session
    session.close()


@pytest.fixture()
def paper_repo():
    return PaperRepository()


@pytest.fixture()
def trade_repo():
    return TradeRepository()


@pytest.fixture()
def gate(paper_repo, trade_repo):
    return PromotionGate(paper_repo=paper_repo, trade_repo=trade_repo)


def _seed_snapshots(session: Session, strategy_id: str, days: int, equity_base: float = 10000.0):
    """Seed daily PnL snapshots for testing."""
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        daily_pnl = 50.0 + (i % 3) * 10  # varying daily PnL
        session.add(PaperPnlSnapshot(
            strategy_id=strategy_id,
            date=d.isoformat(),
            cumulative_pnl=daily_pnl * (i + 1),
            daily_pnl=daily_pnl,
            trade_count=i + 1,
            win_count=max(1, (i + 1) * 2 // 3),
            equity=equity_base + daily_pnl * (i + 1),
        ))
    session.flush()


def _seed_trades(session: Session, strategy_id: str, count: int, win_ratio: float = 0.6):
    """Seed closed trade records."""
    now = datetime.now(timezone.utc)
    wins = int(count * win_ratio)
    for i in range(count):
        is_win = i < wins
        session.add(TradeRecord(
            trade_id=f"trade_{strategy_id}_{i}",
            strategy_name=strategy_id,
            symbol="BTC/USDT",
            timeframe="1h",
            side="long",
            broker="paper",
            entry_price=50000.0,
            entry_quantity=0.01,
            entry_fee=0.5,
            entry_at=now - timedelta(hours=count - i),
            exit_price=51000.0 if is_win else 49000.0,
            exit_quantity=0.01,
            exit_fee=0.5,
            exit_reason="signal",
            exit_at=now - timedelta(hours=count - i - 1),
            profit_abs=10.0 if is_win else -10.0,
            profit_pct=2.0 if is_win else -2.0,
            stake_amount=500.0,
            status="closed",
        ))
    session.flush()


# ---------------------------------------------------------------------------
# PromotionConfig tests
# ---------------------------------------------------------------------------

class TestPromotionConfig:
    def test_defaults(self):
        cfg = PromotionConfig()
        assert cfg.min_days == 7
        assert cfg.min_trades == 10
        assert cfg.min_sharpe == 0.3
        assert cfg.min_win_rate == 0.30
        assert cfg.max_drawdown == -0.20
        assert cfg.min_cumulative_pnl == 0.0

    def test_resolve_global_override(self):
        global_config = {
            "promotion_gates": {"min_days": 14, "min_sharpe": 0.5},
            "timeframe_min_trades": {"1h": 15},
        }
        cfg = resolve_promotion_config(None, global_config)
        assert cfg.min_days == 14
        assert cfg.min_sharpe == 0.5
        assert cfg.min_win_rate == 0.30  # code default

    def test_resolve_strategy_override(self):
        global_config = {
            "promotion_gates": {"min_days": 14, "min_sharpe": 0.5},
            "timeframe_min_trades": {"1h": 15},
        }
        strategy_def = MagicMock(spec=StrategyDefinition)
        strategy_def.promotion_gates = {"min_sharpe": 1.0}
        strategy_def.timeframes = ["1h"]
        cfg = resolve_promotion_config(strategy_def, global_config)
        assert cfg.min_days == 14  # global
        assert cfg.min_sharpe == 1.0  # strategy override
        assert cfg.min_trades == 15  # from timeframe_min_trades

    def test_resolve_timeframe_min_trades(self):
        global_config = {
            "promotion_gates": {},
            "timeframe_min_trades": {"5m": 20, "1d": 5},
        }
        strategy_def = MagicMock(spec=StrategyDefinition)
        strategy_def.promotion_gates = None
        strategy_def.timeframes = ["5m"]
        cfg = resolve_promotion_config(strategy_def, global_config)
        assert cfg.min_trades == 20


# ---------------------------------------------------------------------------
# PromotionGate.evaluate tests
# ---------------------------------------------------------------------------

class TestPromotionGateEvaluate:
    def test_all_criteria_pass(self, db_session, gate):
        """All 6 criteria met -> passed=True."""
        _seed_snapshots(db_session, "strat_a", days=10)
        _seed_trades(db_session, "strat_a", count=15, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=10, min_sharpe=-999, min_win_rate=0.3, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = gate.evaluate("strat_a", config, db_session)
        assert isinstance(result, PromotionResult)
        assert result.passed is True
        assert "days" in result.checks
        assert "trades" in result.checks
        assert "win_rate" in result.checks

    def test_insufficient_days(self, db_session, gate):
        """Days < min_days -> passed=False."""
        _seed_snapshots(db_session, "strat_b", days=3)
        _seed_trades(db_session, "strat_b", count=15, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=5, min_sharpe=-999, min_win_rate=0.1, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = gate.evaluate("strat_b", config, db_session)
        assert result.passed is False
        assert result.checks["days"].passed is False

    def test_insufficient_trades(self, db_session, gate):
        """Trades < min_trades -> passed=False."""
        _seed_snapshots(db_session, "strat_c", days=10)
        _seed_trades(db_session, "strat_c", count=3, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=10, min_sharpe=-999, min_win_rate=0.1, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = gate.evaluate("strat_c", config, db_session)
        assert result.passed is False
        assert result.checks["trades"].passed is False

    def test_low_win_rate(self, db_session, gate):
        """Win rate below threshold -> passed=False."""
        _seed_snapshots(db_session, "strat_d", days=10)
        _seed_trades(db_session, "strat_d", count=20, win_ratio=0.1)
        config = PromotionConfig(min_days=7, min_trades=5, min_sharpe=-999, min_win_rate=0.5, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = gate.evaluate("strat_d", config, db_session)
        assert result.passed is False
        assert result.checks["win_rate"].passed is False

    def test_sharpe_skip_when_few_trades(self, db_session, gate):
        """Sharpe check skipped when < 2 daily data points."""
        _seed_snapshots(db_session, "strat_e", days=1)
        _seed_trades(db_session, "strat_e", count=15, win_ratio=0.6)
        config = PromotionConfig(min_days=1, min_trades=5, min_sharpe=0.5, min_win_rate=0.1, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = gate.evaluate("strat_e", config, db_session)
        # Sharpe check should have actual=None (skipped)
        sharpe_check = result.checks.get("sharpe")
        assert sharpe_check is not None
        assert sharpe_check.actual is None
        assert sharpe_check.passed is True  # skipped = pass

    def test_max_drawdown_fail(self, db_session, gate):
        """Max drawdown exceeds threshold -> passed=False."""
        # Create equity curve with large drawdown
        today = datetime.now(timezone.utc).date()
        for i in range(10):
            d = today - timedelta(days=9 - i)
            # Peak at day 3, trough at day 7 -> 50% drawdown
            if i <= 3:
                equity = 10000 + i * 1000
            elif i <= 7:
                equity = 13000 - (i - 3) * 2000
            else:
                equity = 5000 + (i - 7) * 500
            db_session.add(PaperPnlSnapshot(
                strategy_id="strat_f",
                date=d.isoformat(),
                cumulative_pnl=equity - 10000,
                daily_pnl=100,
                trade_count=i + 1,
                win_count=i,
                equity=equity,
            ))
        db_session.flush()
        _seed_trades(db_session, "strat_f", count=15, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=5, min_sharpe=-999, min_win_rate=0.1, max_drawdown=-0.20, min_cumulative_pnl=-99999)
        result = gate.evaluate("strat_f", config, db_session)
        assert result.passed is False
        assert result.checks["max_drawdown"].passed is False

    def test_summary_lists_failures(self, db_session, gate):
        """Summary string lists all failed checks."""
        _seed_snapshots(db_session, "strat_g", days=3)
        _seed_trades(db_session, "strat_g", count=2, win_ratio=0.5)
        config = PromotionConfig(min_days=7, min_trades=10)
        result = gate.evaluate("strat_g", config, db_session)
        assert result.passed is False
        assert len(result.summary) > 0

    def test_estimated_promotion_present(self, db_session, gate):
        """estimated_promotion is not None when criteria are not met."""
        _seed_snapshots(db_session, "strat_h", days=3)
        _seed_trades(db_session, "strat_h", count=5, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=10)
        result = gate.evaluate("strat_h", config, db_session)
        assert result.passed is False
        assert result.estimated_promotion is not None

    def test_backtest_sharpe_blocks_when_paper_below_baseline(self, db_session, paper_repo, trade_repo):
        """Paper Sharpe < backtest baseline -> backtest_sharpe check fails, result fails."""
        _seed_snapshots(db_session, "strat_bt1", days=10)
        _seed_trades(db_session, "strat_bt1", count=15, win_ratio=0.6)

        mock_bt_repo = MagicMock(spec=BacktestRepository)
        mock_bt_repo.get_history.return_value = [MagicMock(sharpe_ratio=9999.0)]  # very high baseline

        gate = PromotionGate(paper_repo, trade_repo, backtest_repo=mock_bt_repo)
        config = PromotionConfig(min_days=1, min_trades=1, min_sharpe=-999, min_win_rate=0.0, max_drawdown=-0.99, min_cumulative_pnl=-99999)
        result = gate.evaluate("strat_bt1", config, db_session)

        assert "backtest_sharpe" in result.checks
        assert result.checks["backtest_sharpe"].passed is False
        assert result.passed is False

    def test_backtest_sharpe_passes_when_paper_above_baseline(self, db_session, paper_repo, trade_repo):
        """Paper Sharpe > backtest baseline -> backtest_sharpe check passes."""
        _seed_snapshots(db_session, "strat_bt2", days=10)
        _seed_trades(db_session, "strat_bt2", count=15, win_ratio=0.6)

        mock_bt_repo = MagicMock(spec=BacktestRepository)
        mock_bt_repo.get_history.return_value = [MagicMock(sharpe_ratio=0.001)]  # very low baseline

        gate = PromotionGate(paper_repo, trade_repo, backtest_repo=mock_bt_repo)
        config = PromotionConfig(min_days=1, min_trades=1, min_sharpe=-999, min_win_rate=0.0, max_drawdown=-0.99, min_cumulative_pnl=-99999)
        result = gate.evaluate("strat_bt2", config, db_session)

        assert "backtest_sharpe" in result.checks
        assert result.checks["backtest_sharpe"].passed is True

    def test_no_backtest_record_skips_check(self, db_session, paper_repo, trade_repo):
        """backtest_repo.get_history returns [] -> no backtest_sharpe check."""
        _seed_snapshots(db_session, "strat_bt3", days=10)
        _seed_trades(db_session, "strat_bt3", count=15, win_ratio=0.6)

        mock_bt_repo = MagicMock(spec=BacktestRepository)
        mock_bt_repo.get_history.return_value = []

        gate = PromotionGate(paper_repo, trade_repo, backtest_repo=mock_bt_repo)
        config = PromotionConfig(min_days=1, min_trades=1, min_sharpe=-999, min_win_rate=0.0, max_drawdown=-0.99, min_cumulative_pnl=-99999)
        result = gate.evaluate("strat_bt3", config, db_session)

        assert "backtest_sharpe" not in result.checks

    def test_no_backtest_repo_skips_check(self, db_session, paper_repo, trade_repo):
        """PromotionGate without backtest_repo -> no backtest_sharpe check at all."""
        _seed_snapshots(db_session, "strat_bt4", days=10)
        _seed_trades(db_session, "strat_bt4", count=15, win_ratio=0.6)

        gate = PromotionGate(paper_repo, trade_repo)  # no backtest_repo
        config = PromotionConfig(min_days=1, min_trades=1, min_sharpe=-999, min_win_rate=0.0, max_drawdown=-0.99, min_cumulative_pnl=-99999)
        result = gate.evaluate("strat_bt4", config, db_session)

        assert "backtest_sharpe" not in result.checks


# ---------------------------------------------------------------------------
# LifecycleManager integration tests
# ---------------------------------------------------------------------------

class TestLifecycleManagerGate:
    def _make_registry(self, tmp_path: Path, status: str = "paper") -> Path:
        registry = tmp_path / "registry.json"
        registry.write_text(json.dumps({
            "strategies": [{
                "id": "strat_x",
                "name": "Test Strategy",
                "status": status,
                "status_history": [{"from": None, "to": "draft", "date": "2026-01-01"}],
            }]
        }))
        return registry

    def test_paper_to_active_requires_gate(self, tmp_path):
        """paper->active without gate raises InvalidTransitionError."""
        registry = self._make_registry(tmp_path)
        mgr = LifecycleManager(registry_path=registry)
        with pytest.raises(InvalidTransitionError, match="PromotionGate"):
            mgr.transition("strat_x", "active")

    def test_paper_to_active_gate_fail(self, tmp_path, db_session, gate):
        """paper->active with failing gate raises InvalidTransitionError."""
        registry = self._make_registry(tmp_path)
        mgr = LifecycleManager(registry_path=registry)
        # No data -> all checks fail
        config = PromotionConfig()
        with pytest.raises(InvalidTransitionError, match="승격 기준 미충족"):
            mgr.transition("strat_x", "active", gate=gate, gate_config=config, session=db_session)

    def test_paper_to_active_gate_pass(self, tmp_path, db_session, gate):
        """paper->active with passing gate succeeds."""
        registry = self._make_registry(tmp_path)
        mgr = LifecycleManager(registry_path=registry)
        _seed_snapshots(db_session, "strat_x", days=10)
        _seed_trades(db_session, "strat_x", count=15, win_ratio=0.6)
        config = PromotionConfig(min_days=7, min_trades=5, min_sharpe=-999, min_win_rate=0.1, max_drawdown=-0.99, min_cumulative_pnl=0.0)
        result = mgr.transition("strat_x", "active", gate=gate, gate_config=config, session=db_session)
        assert result["status"] == "active"

    def test_other_transitions_ignore_gate(self, tmp_path):
        """Non paper->active transitions don't require gate."""
        registry = self._make_registry(tmp_path, status="draft")
        mgr = LifecycleManager(registry_path=registry)
        # draft->testing should work without gate
        result = mgr.transition("strat_x", "testing")
        assert result["status"] == "testing"


# ---------------------------------------------------------------------------
# StrategyDefinition extension
# ---------------------------------------------------------------------------

class TestStrategyDefinitionPromotionGates:
    def test_promotion_gates_field_exists(self):
        """StrategyDefinition has promotion_gates optional field."""
        assert hasattr(StrategyDefinition, "model_fields")
        assert "promotion_gates" in StrategyDefinition.model_fields

    def test_promotion_gates_default_none(self):
        """promotion_gates defaults to None."""
        # Create minimal valid StrategyDefinition
        sd = StrategyDefinition(
            name="test",
            markets=["crypto_futures"],
            indicators=[{"name": "RSI", "params": {"timeperiod": 14}, "output": "rsi"}],
            entry={"conditions": [{"left": "rsi", "op": "lt", "right": 30}]},
            exit={"conditions": [{"left": "rsi", "op": "gt", "right": 70}]},
        )
        assert sd.promotion_gates is None

    def test_promotion_gates_with_values(self):
        sd = StrategyDefinition(
            name="test",
            markets=["crypto_futures"],
            indicators=[{"name": "RSI", "params": {"timeperiod": 14}, "output": "rsi"}],
            entry={"conditions": [{"left": "rsi", "op": "lt", "right": 30}]},
            exit={"conditions": [{"left": "rsi", "op": "gt", "right": 70}]},
            promotion_gates={"min_sharpe": 1.0, "min_days": 14},
        )
        assert sd.promotion_gates == {"min_sharpe": 1.0, "min_days": 14}

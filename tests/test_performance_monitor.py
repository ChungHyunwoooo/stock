"""StrategyPerformanceMonitor unit tests."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.core.json_store import JsonRuntimeStore
from engine.core.models import (
    TradingMode,
    TradingRuntimeState,
    TradingSignal,
    SignalAction,
    TradeSide,
)
from engine.strategy.performance_monitor import (
    PerformanceConfig,
    PerformanceSnapshot,
    StrategyPerformanceMonitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(profit_pct: float, strategy_name: str = "strat_a") -> MagicMock:
    t = MagicMock()
    t.profit_pct = profit_pct
    t.strategy_name = strategy_name
    return t


def _make_backtest(sharpe: float, win_rate: float) -> MagicMock:
    bt = MagicMock()
    bt.sharpe_ratio = sharpe
    bt.result_json = json.dumps({"win_rate": win_rate})
    return bt


def _build_monitor(
    trades: list | None = None,
    backtests: list | None = None,
    active_strategies: list[dict] | None = None,
    config: PerformanceConfig | None = None,
) -> StrategyPerformanceMonitor:
    trade_repo = MagicMock()
    trade_repo.list_closed.return_value = trades or []

    backtest_repo = MagicMock()
    backtest_repo.get_history.return_value = backtests or []

    lifecycle = MagicMock()
    lifecycle.list_by_status.return_value = active_strategies or []

    runtime_store = MagicMock()
    state = TradingRuntimeState()
    runtime_store.load.return_value = state

    notifier = MagicMock()

    return StrategyPerformanceMonitor(
        trade_repo=trade_repo,
        backtest_repo=backtest_repo,
        lifecycle=lifecycle,
        runtime_store=runtime_store,
        notifier=notifier,
        config=config or PerformanceConfig(),
    )


# ---------------------------------------------------------------------------
# _compute_rolling_metrics
# ---------------------------------------------------------------------------


class TestComputeRollingMetrics:
    def test_normal(self):
        """20건 trades -> sharpe, win_rate 계산."""
        profits = [2.0, -1.0, 1.5, 3.0, -0.5] * 4  # 20 trades
        trades = [_make_trade(p) for p in profits]

        monitor = _build_monitor()
        sharpe, win_rate = monitor._compute_rolling_metrics(trades, window=20)

        assert sharpe is not None
        assert win_rate is not None

        # win_rate: 12 wins / 20 = 0.6
        assert win_rate == pytest.approx(0.6)

        # sharpe: mean / std of profits
        import statistics
        mean = statistics.mean(profits)
        std = statistics.stdev(profits)
        assert sharpe == pytest.approx(mean / std, rel=1e-6)

    def test_insufficient(self):
        """window 미만 -> (None, None)."""
        trades = [_make_trade(1.0) for _ in range(5)]
        monitor = _build_monitor()
        sharpe, win_rate = monitor._compute_rolling_metrics(trades, window=20)

        assert sharpe is None
        assert win_rate is None

    def test_zero_std(self):
        """모든 profit_pct 동일 -> std=0 -> sharpe=0."""
        trades = [_make_trade(1.0) for _ in range(20)]
        monitor = _build_monitor()
        sharpe, win_rate = monitor._compute_rolling_metrics(trades, window=20)

        assert sharpe == 0.0
        assert win_rate == 1.0


# ---------------------------------------------------------------------------
# _evaluate_strategy
# ---------------------------------------------------------------------------


class TestEvaluateStrategy:
    def test_warning(self):
        """baseline sharpe=1.0, rolling sharpe=0.8 (20% drop) -> warning."""
        profits = [2.0, -1.0, 1.5, 3.0, -0.5] * 4
        trades = [_make_trade(p) for p in profits]
        backtests = [_make_backtest(sharpe=1.0, win_rate=0.8)]

        monitor = _build_monitor(trades=trades, backtests=backtests)
        session = MagicMock()

        snapshot = monitor._evaluate_strategy(session, "strat_a")

        # Rolling sharpe ~ 0.65, baseline=1.0 -> degradation > 15%
        assert snapshot.alert_level == "warning"

    def test_critical(self):
        """30거래 rolling sharpe < -0.5 -> critical."""
        profits = [-3.0, -2.0, 1.0, -4.0, -1.0, -2.5] * 5  # 30 trades, heavily negative
        trades = [_make_trade(p) for p in profits]
        backtests = [_make_backtest(sharpe=1.0, win_rate=0.5)]

        monitor = _build_monitor(trades=trades, backtests=backtests)
        session = MagicMock()

        snapshot = monitor._evaluate_strategy(session, "strat_a")

        assert snapshot.alert_level == "critical"

    def test_healthy(self):
        """baseline 대비 10% 미만 하락 -> none."""
        # Rolling sharpe close to baseline
        profits = [2.5, -0.5, 3.0, 1.0, -0.2] * 4  # 20 trades, good sharpe
        trades = [_make_trade(p) for p in profits]

        import statistics
        mean = statistics.mean(profits)
        std = statistics.stdev(profits)
        actual_sharpe = mean / std

        # Baseline slightly above actual -> degradation < 15%
        backtests = [_make_backtest(sharpe=actual_sharpe * 1.05, win_rate=0.6)]

        monitor = _build_monitor(trades=trades, backtests=backtests)
        session = MagicMock()

        snapshot = monitor._evaluate_strategy(session, "strat_a")

        assert snapshot.alert_level == "none"

    def test_no_baseline(self):
        """baseline 없으면 degradation 계산 skip, Sharpe만 체크."""
        profits = [1.0] * 20
        trades = [_make_trade(p) for p in profits]
        backtests = []  # no baseline

        monitor = _build_monitor(trades=trades, backtests=backtests)
        session = MagicMock()

        snapshot = monitor._evaluate_strategy(session, "strat_a")

        assert snapshot.baseline_sharpe is None
        assert snapshot.alert_level == "none"


# ---------------------------------------------------------------------------
# paused_strategies serialization
# ---------------------------------------------------------------------------


class TestPausedStrategiesSerialization:
    def test_roundtrip(self):
        """JsonRuntimeStore가 paused_strategies를 정상 직렬화/역직렬화."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = JsonRuntimeStore(path)

            state = TradingRuntimeState()
            state.paused_strategies = {"strat_a", "strat_b"}
            store.save(state)

            loaded = store.load()
            assert loaded.paused_strategies == {"strat_a", "strat_b"}

    def test_missing_field_defaults_empty(self):
        """기존 state.json에 paused_strategies 없으면 빈 set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            # Write legacy format without paused_strategies
            path.write_text(json.dumps({
                "mode": "alert_only",
                "broker": "paper",
                "paused": False,
                "automation_enabled": True,
                "pending_orders": [],
                "executions": [],
                "positions": [],
                "updated_at": "",
            }))

            store = JsonRuntimeStore(path)
            loaded = store.load()
            assert loaded.paused_strategies == set()


# ---------------------------------------------------------------------------
# Orchestrator per-strategy pause
# ---------------------------------------------------------------------------


class TestOrchestratorSkipsPausedStrategy:
    def test_signal_skipped(self):
        """paused_strategies에 전략 추가 후 process_signal 호출 시 신호 무시."""
        from engine.application.trading.orchestrator import TradingOrchestrator

        runtime_store = MagicMock()
        state = TradingRuntimeState(mode=TradingMode.auto)
        state.paused_strategies = {"strat_paused"}
        runtime_store.load.return_value = state

        notifier = MagicMock()
        broker = MagicMock()

        orch = TradingOrchestrator(
            runtime_store=runtime_store,
            notifier=notifier,
            broker=broker,
        )

        signal = TradingSignal(
            strategy_id="strat_paused",
            symbol="BTCUSDT",
            timeframe="5m",
            action=SignalAction.entry,
            side=TradeSide.long,
            entry_price=50000.0,
        )

        result = orch.process_signal(signal)

        # Broker should NOT have been called
        broker.execute_order.assert_not_called()

        # Notifier should have sent skip text
        notifier.send_text.assert_called_once()
        msg = notifier.send_text.call_args[0][0]
        assert "paused" in msg.lower()
        assert "strat_paused" in msg

    def test_non_paused_strategy_executes(self):
        """paused_strategies에 없는 전략은 정상 실행."""
        from engine.application.trading.orchestrator import TradingOrchestrator

        runtime_store = MagicMock()
        state = TradingRuntimeState(mode=TradingMode.auto)
        state.paused_strategies = {"other_strat"}
        runtime_store.load.return_value = state

        notifier = MagicMock()
        broker = MagicMock()
        execution = MagicMock()
        broker.execute_order.return_value = execution

        orch = TradingOrchestrator(
            runtime_store=runtime_store,
            notifier=notifier,
            broker=broker,
        )

        signal = TradingSignal(
            strategy_id="active_strat",
            symbol="BTCUSDT",
            timeframe="5m",
            action=SignalAction.entry,
            side=TradeSide.long,
            entry_price=50000.0,
        )

        result = orch.process_signal(signal)

        broker.execute_order.assert_called_once()

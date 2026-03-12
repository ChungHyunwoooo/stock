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
        from engine.strategy.position_sizer import PositionSizeResult
        import pandas as pd

        runtime_store = MagicMock()
        state = TradingRuntimeState(mode=TradingMode.auto)
        state.paused_strategies = {"other_strat"}
        runtime_store.load.return_value = state

        notifier = MagicMock()
        broker = MagicMock()
        execution = MagicMock()
        broker.execute_order.return_value = execution
        broker.fetch_available.return_value = 10000.0

        sizer = MagicMock()
        sizer.calculate.return_value = PositionSizeResult(
            quantity=1.0, risk_amount=5.0, position_value=100.0,
            kelly_applied=False, allocation_weight=1.0, size_factor=1.0, reason="test",
        )
        pr = MagicMock()
        pr.get_allocation_weights.return_value = {"active_strat": 1.0}
        pr.check_correlation_gate.return_value = (True, "passed")

        orch = TradingOrchestrator(
            runtime_store=runtime_store,
            notifier=notifier,
            broker=broker,
            position_sizer=sizer,
            portfolio_risk=pr,
        )

        signal = TradingSignal(
            strategy_id="active_strat",
            symbol="BTCUSDT",
            timeframe="5m",
            action=SignalAction.entry,
            side=TradeSide.long,
            entry_price=50000.0,
            metadata={
                "ohlcv_df": pd.DataFrame(
                    {"open": [50000.0], "high": [51000.0], "low": [49000.0], "close": [50500.0], "volume": [100.0]}
                ),
                "returns": pd.Series([0.01, -0.005]),
            },
        )

        result = orch.process_signal(signal)

        broker.execute_order.assert_called_once()


# ---------------------------------------------------------------------------
# Discord embed alert + auto-pause (05-02)
# ---------------------------------------------------------------------------


def _make_snapshot(
    strategy_id: str = "strat_a",
    alert_level: str = "none",
    rolling_sharpe: float | None = 0.5,
    baseline_sharpe: float | None = 1.0,
    degradation_pct_sharpe: float | None = None,
    rolling_win_rate: float | None = 0.6,
    baseline_win_rate: float | None = 0.7,
    degradation_pct_win_rate: float | None = None,
) -> PerformanceSnapshot:
    return PerformanceSnapshot(
        strategy_id=strategy_id,
        rolling_sharpe=rolling_sharpe,
        baseline_sharpe=baseline_sharpe,
        degradation_pct_sharpe=degradation_pct_sharpe,
        rolling_win_rate=rolling_win_rate,
        baseline_win_rate=baseline_win_rate,
        degradation_pct_win_rate=degradation_pct_win_rate,
        alert_level=alert_level,
    )


class TestWarningAlert:
    def test_warning_sends_alert(self):
        """WARNING snapshot -> MemoryNotifier에 perf_alert:warning 기록."""
        from engine.notifications.discord_webhook import MemoryNotifier

        notifier = MemoryNotifier()
        snap = _make_snapshot(alert_level="warning", strategy_id="s1")

        result = notifier.send_performance_alert(snap)

        assert result is True
        assert any("perf_alert:warning:s1" in m for m in notifier.messages)


class TestCriticalAlert:
    def test_critical_sends_alert_and_pauses(self):
        """CRITICAL snapshot -> alert + paused_strategies에 추가."""
        from engine.notifications.discord_webhook import MemoryNotifier

        notifier = MemoryNotifier()
        runtime_store = MagicMock()
        state = TradingRuntimeState()
        runtime_store.load.return_value = state

        monitor = _build_monitor()
        monitor.notifier = notifier
        monitor.runtime_store = runtime_store

        snap = _make_snapshot(alert_level="critical", strategy_id="s2")
        monitor._handle_critical(snap.strategy_id, snap)

        assert any("perf_alert:critical:s2" in m for m in notifier.messages)
        assert "s2" in state.paused_strategies

    def test_healthy_no_alert(self):
        """alert_level='none' -> 알림 미발송."""
        from engine.notifications.discord_webhook import MemoryNotifier

        notifier = MemoryNotifier()
        snap = _make_snapshot(alert_level="none", strategy_id="s3")

        result = notifier.send_performance_alert(snap)

        assert result is True
        assert not any("perf_alert" in m for m in notifier.messages)


class TestDiscordEmbed:
    def test_discord_embed_warning_color(self):
        """WARNING embed color=0xFFA500."""
        from engine.notifications.discord_webhook import DiscordWebhookNotifier

        notifier = DiscordWebhookNotifier()
        snap = _make_snapshot(alert_level="warning", strategy_id="s1")

        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.send_performance_alert(snap)
            payload = mock_post.call_args[0][0]
            embed = payload["embeds"][0]
            assert embed["color"] == 0xFFA500
            assert "[WARNING]" in embed["title"]

    def test_discord_embed_critical_color(self):
        """CRITICAL embed color=0xFF0000."""
        from engine.notifications.discord_webhook import DiscordWebhookNotifier

        notifier = DiscordWebhookNotifier()
        snap = _make_snapshot(alert_level="critical", strategy_id="s1")

        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.send_performance_alert(snap)
            payload = mock_post.call_args[0][0]
            embed = payload["embeds"][0]
            assert embed["color"] == 0xFF0000
            assert "[CRITICAL]" in embed["title"]

    def test_embed_fields_contain_metrics(self):
        """embed fields에 Sharpe/승률/저하율 포함."""
        from engine.notifications.discord_webhook import DiscordWebhookNotifier

        notifier = DiscordWebhookNotifier()
        snap = _make_snapshot(
            alert_level="warning",
            rolling_sharpe=0.5,
            baseline_sharpe=1.0,
            degradation_pct_sharpe=0.5,
            rolling_win_rate=0.4,
            baseline_win_rate=0.6,
            degradation_pct_win_rate=0.33,
        )

        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.send_performance_alert(snap)
            payload = mock_post.call_args[0][0]
            embed = payload["embeds"][0]
            field_names = [f["name"] for f in embed["fields"]]
            # Must contain key metric fields
            assert any("Sharpe" in n for n in field_names)
            assert any("승률" in n or "Win" in n for n in field_names)


class TestMultipleStrategiesIndependent:
    def test_only_critical_strategy_paused(self):
        """2개 전략 중 1개만 CRITICAL -> 해당 전략만 pause."""
        from engine.notifications.discord_webhook import MemoryNotifier

        notifier = MemoryNotifier()
        runtime_store = MagicMock()
        state = TradingRuntimeState()
        runtime_store.load.return_value = state

        monitor = _build_monitor()
        monitor.notifier = notifier
        monitor.runtime_store = runtime_store

        # Only s_bad is critical
        snap_bad = _make_snapshot(alert_level="critical", strategy_id="s_bad")
        snap_good = _make_snapshot(alert_level="none", strategy_id="s_good")

        monitor._handle_critical(snap_bad.strategy_id, snap_bad)

        assert "s_bad" in state.paused_strategies
        assert "s_good" not in state.paused_strategies

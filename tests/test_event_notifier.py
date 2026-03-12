"""Tests for EventNotifier -- verifies 4 event type message formats + integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.core.models import BrokerKind, ExecutionRecord, SignalAction, TradeSide
from engine.notifications.discord_webhook import MemoryNotifier
from engine.notifications.event_notifier import EventNotifier
from engine.strategy.lifecycle_manager import LifecycleManager


def _make_notifier() -> tuple[EventNotifier, MemoryNotifier]:
    mem = MemoryNotifier()
    return EventNotifier(mem), mem


class TestNotifyExecution:
    def test_execution_message_format(self) -> None:
        en, mem = _make_notifier()
        execution = ExecutionRecord(
            order_id="ord-001",
            signal_id="sig-001",
            symbol="BTC/USDT",
            action=SignalAction.entry,
            side=TradeSide.long,
            quantity=0.5,
            price=65000.0,
            broker=BrokerKind.paper,
            status="filled",
        )
        result = en.notify_execution(execution)

        assert result is True
        assert len(mem.messages) == 1
        msg = mem.messages[0]
        assert "[EXECUTION]" in msg
        assert "BTC/USDT" in msg
        assert "LONG" in msg
        assert "0.5" in msg
        assert "65,000.0000" in msg
        assert "paper" in msg


class TestNotifyLifecycleTransition:
    def test_transition_message_format(self) -> None:
        en, mem = _make_notifier()
        result = en.notify_lifecycle_transition(
            "rsi_divergence", "testing", "paper", reason="backtest passed"
        )

        assert result is True
        assert len(mem.messages) == 1
        msg = mem.messages[0]
        assert "[LIFECYCLE]" in msg
        assert "rsi_divergence" in msg
        assert "testing -> paper" in msg
        assert "backtest passed" in msg

    def test_transition_without_reason(self) -> None:
        en, mem = _make_notifier()
        en.notify_lifecycle_transition("ema_cross", "draft", "testing")

        msg = mem.messages[0]
        assert "[LIFECYCLE]" in msg
        assert "ema_cross: draft -> testing" in msg
        assert "(" not in msg


class TestNotifySystemError:
    def test_warning_message_format(self) -> None:
        en, mem = _make_notifier()
        result = en.notify_system_error(
            "ScalpingRunner", "WebSocket timeout after 30s"
        )

        assert result is True
        msg = mem.messages[0]
        assert "[WARNING]" in msg
        assert "ScalpingRunner" in msg
        assert "WebSocket timeout after 30s" in msg

    def test_critical_severity(self) -> None:
        en, mem = _make_notifier()
        en.notify_system_error("DBPool", "Connection pool exhausted", severity="CRITICAL")

        msg = mem.messages[0]
        assert "[CRITICAL]" in msg
        assert "DBPool" in msg


class TestNotifyBacktestComplete:
    def test_backtest_message_format(self) -> None:
        en, mem = _make_notifier()
        result = en.notify_backtest_complete(
            strategy_id="rsi_divergence",
            symbol="BTC/USDT",
            sharpe=1.23,
            total_return=0.152,
            max_dd=-0.081,
        )

        assert result is True
        msg = mem.messages[0]
        assert "[BACKTEST]" in msg
        assert "rsi_divergence" in msg
        assert "BTC/USDT" in msg
        assert "Sharpe 1.23" in msg
        assert "Return +15.2%" in msg
        assert "MaxDD -8.1%" in msg

    def test_backtest_with_none_values(self) -> None:
        en, mem = _make_notifier()
        en.notify_backtest_complete(
            strategy_id="test_strat",
            symbol="ETH/USDT",
            sharpe=None,
            total_return=0.05,
            max_dd=None,
        )

        msg = mem.messages[0]
        assert "Sharpe N/A" in msg
        assert "MaxDD N/A" in msg
        assert "Return +5.0%" in msg


class TestLifecycleCallbackIntegration:
    """LifecycleManager transition -> callback -> EventNotifier -> MemoryNotifier."""

    def _make_registry(self, tmp_path: Path) -> Path:
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(json.dumps({
            "strategies": [{
                "id": "test_strat",
                "name": "Test Strategy",
                "status": "draft",
                "status_history": [],
            }]
        }))
        return registry_path

    def test_transition_fires_callback(self, tmp_path: Path) -> None:
        registry_path = self._make_registry(tmp_path)
        en, mem = _make_notifier()
        lm = LifecycleManager(registry_path=registry_path)
        lm.add_transition_listener(
            lambda sid, fr, to: en.notify_lifecycle_transition(sid, fr, to)
        )

        lm.transition("test_strat", "testing", reason="unit test")

        assert len(mem.messages) == 1
        msg = mem.messages[0]
        assert "[LIFECYCLE]" in msg
        assert "test_strat" in msg
        assert "draft -> testing" in msg

    def test_callback_error_does_not_block_transition(self, tmp_path: Path) -> None:
        registry_path = self._make_registry(tmp_path)
        lm = LifecycleManager(registry_path=registry_path)

        def bad_callback(sid: str, fr: str, to: str) -> None:
            raise RuntimeError("callback boom")

        lm.add_transition_listener(bad_callback)
        entry = lm.transition("test_strat", "testing")

        assert entry["status"] == "testing"


# --- Phase 10 Task 1 tests ---


class TestBootstrapWiring:
    """build_trading_runtime() creates EventNotifier and injects into orchestrator."""

    @patch("engine.strategy.performance_monitor.StrategyPerformanceMonitor.run_daemon")
    def test_orchestrator_has_event_notifier(self, mock_daemon: MagicMock) -> None:
        from engine.interfaces.bootstrap import build_trading_runtime, TradingRuntimeConfig

        runtime = build_trading_runtime(TradingRuntimeConfig(
            notifier_plugin="memory",
            broker_plugin="paper",
        ))

        assert runtime.orchestrator.event_notifier is not None
        assert isinstance(runtime.event_notifier, EventNotifier)


class TestBacktestRunnerNotification:
    """BacktestRunner(event_notifier=en).run() sends [BACKTEST] on completion."""

    def test_run_sends_backtest_notification(self) -> None:
        import pandas as pd
        from engine.backtest.runner import BacktestRunner
        from engine.schema import (
            Condition, ConditionGroup, ConditionOp, Direction,
            IndicatorDef, MarketType, RiskParams, StrategyDefinition, StrategyStatus,
        )

        en, mem = _make_notifier()
        runner = BacktestRunner(auto_save=False, event_notifier=en)

        strategy = StrategyDefinition(
            name="test_notify",
            version="1.0",
            status=StrategyStatus.draft,
            markets=[MarketType.crypto_spot],
            direction=Direction.long,
            timeframes=["1d"],
            indicators=[IndicatorDef(name="rsi", params={"period": 14}, output="rsi_14")],
            entry=ConditionGroup(logic="and", conditions=[Condition(left="rsi_14", op=ConditionOp.lt, right=30)]),
            exit=ConditionGroup(logic="and", conditions=[Condition(left="rsi_14", op=ConditionOp.gt, right=70)]),
            risk=RiskParams(),
        )

        # Mock data provider to return simple data
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {"open": [100]*5, "high": [105]*5, "low": [95]*5, "close": [100]*5, "volume": [1000]*5},
            index=dates,
        )

        with patch("engine.backtest.runner.get_provider") as mock_provider:
            mock_provider.return_value.fetch_ohlcv.return_value = df
            runner.run(strategy, symbol="BTC/USDT", start="2024-01-01", end="2024-01-05")

        assert len(mem.messages) == 1
        assert "[BACKTEST]" in mem.messages[0]
        assert "test_notify" in mem.messages[0]


class TestBacktestRunnerBackwardCompat:
    """BacktestRunner() no-arg construction still works."""

    def test_no_arg_construction(self) -> None:
        from engine.backtest.runner import BacktestRunner

        runner = BacktestRunner()
        assert runner._event_notifier is None


class TestBacktestHistoryRegistered:
    """BacktestHistoryPlugin is in DEFAULT_COMMAND_PLUGINS."""

    def test_plugin_registered(self) -> None:
        from engine.interfaces.discord.commands import DEFAULT_COMMAND_PLUGINS
        from engine.interfaces.discord.commands.backtest_history import BacktestHistoryPlugin

        assert any(isinstance(p, BacktestHistoryPlugin) for p in DEFAULT_COMMAND_PLUGINS)


class TestSystemErrorNotification:
    """notify_system_error sends [CRITICAL] or [WARNING] message."""

    def test_system_error_message(self) -> None:
        en, mem = _make_notifier()
        en.notify_system_error(component="bootstrap", error="test error", severity="CRITICAL")

        assert len(mem.messages) == 1
        assert "[CRITICAL]" in mem.messages[0]
        assert "bootstrap" in mem.messages[0]
        assert "test error" in mem.messages[0]

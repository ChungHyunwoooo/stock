"""Tests for EventNotifier -- verifies 4 event type message formats + integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

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

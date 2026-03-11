"""Tests for format_status_embed (Discord /status command formatting)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from engine.core.models import (
    BrokerKind,
    ExecutionRecord,
    Position,
    PositionStatus,
    SignalAction,
    TradeSide,
    TradingMode,
    TradingRuntimeState,
)
from engine.interfaces.discord.formatting import format_status_embed
from engine.strategy.lifecycle_manager import LifecycleManager


def _make_control(state: TradingRuntimeState) -> MagicMock:
    control = MagicMock()
    control.get_state.return_value = state
    return control


def _make_lifecycle(strategies: list[dict] | None = None, error: Exception | None = None) -> MagicMock:
    lm = MagicMock(spec=LifecycleManager)
    if error:
        lm.list_by_status.side_effect = error
    else:
        lm.list_by_status.return_value = strategies or []
    return lm


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yesterday_str() -> str:
    from datetime import timedelta
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestFormatStatusEmbed:
    """format_status_embed unit tests."""

    def test_with_open_positions(self):
        state = TradingRuntimeState(
            positions=[
                Position(
                    position_id="p1",
                    symbol="BTCUSDT",
                    side=TradeSide.long,
                    quantity=0.1,
                    entry_price=50000.0,
                ),
            ]
        )
        result = format_status_embed(_make_control(state), _make_lifecycle())
        assert "BTCUSDT" in result
        assert "long" in result
        assert "entry=50000.0" in result

    def test_no_open_positions(self):
        state = TradingRuntimeState(positions=[])
        result = format_status_embed(_make_control(state), _make_lifecycle())
        assert "No open positions" in result

    def test_strategy_status_counts(self):
        strategies = [
            {"id": "s1", "status": "active"},
            {"id": "s2", "status": "active"},
            {"id": "s3", "status": "paper"},
            {"id": "s4", "status": "testing"},
        ]
        state = TradingRuntimeState()
        result = format_status_embed(_make_control(state), _make_lifecycle(strategies))
        assert "active: 2" in result
        assert "paper: 1" in result
        assert "testing: 1" in result

    def test_daily_pnl_with_today_trades(self):
        state = TradingRuntimeState(
            executions=[
                ExecutionRecord(
                    order_id="o1", signal_id="s1", symbol="BTCUSDT",
                    action=SignalAction.entry, side=TradeSide.long,
                    quantity=0.1, price=50000.0, broker=BrokerKind.paper,
                    status="filled", notes="0.05", executed_at=_today_str(),
                ),
                ExecutionRecord(
                    order_id="o2", signal_id="s2", symbol="ETHUSDT",
                    action=SignalAction.entry, side=TradeSide.long,
                    quantity=1.0, price=3000.0, broker=BrokerKind.paper,
                    status="filled", notes="-0.02", executed_at=_today_str(),
                ),
            ]
        )
        result = format_status_embed(_make_control(state), _make_lifecycle())
        assert "Trades: 2" in result
        assert "Realized PnL: +0.0300" in result

    def test_no_trades_today(self):
        state = TradingRuntimeState(executions=[])
        result = format_status_embed(_make_control(state), _make_lifecycle())
        assert "No trades today" in result

    def test_runtime_section(self):
        state = TradingRuntimeState(
            mode=TradingMode.auto,
            paused=True,
            automation_enabled=False,
        )
        result = format_status_embed(_make_control(state), _make_lifecycle())
        assert "mode=auto" in result
        assert "paused=True" in result
        assert "automation=False" in result

    def test_defer_pattern_in_plugin(self):
        """StatusCommandPlugin uses defer() + followup.send() pattern."""
        from engine.interfaces.discord.commands.status import StatusCommandPlugin
        import inspect
        source = inspect.getsource(StatusCommandPlugin)
        assert "defer()" in source
        assert "followup.send" in source

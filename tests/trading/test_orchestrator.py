
from unittest.mock import MagicMock

import pandas as pd

from engine.application.trading import TradingControlService, TradingOrchestrator
from engine.core import SignalAction, TradeSide, TradingMode, TradingSignal
from engine.core.models import ExecutionRecord, OrderRequest, Position, PositionStatus, utc_now_iso, TradingRuntimeState
from engine.notifications import MemoryNotifier
from engine.core import JsonRuntimeStore
from engine.strategy.position_sizer import PositionSizeResult


def _mock_broker() -> MagicMock:
    """BrokerPort mock that returns a realistic ExecutionRecord."""
    broker = MagicMock()

    def _execute(order: OrderRequest, state: TradingRuntimeState) -> ExecutionRecord:
        rec = ExecutionRecord(
            order_id=f"mock-{order.signal_id}",
            signal_id=order.signal_id,
            symbol=order.symbol,
            action=order.action,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            status="filled",
            executed_at=utc_now_iso(),
        )
        # Mimic position update like real broker
        pos = Position(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            entry_price=order.price,
            status=PositionStatus.open,
        )
        state.positions.append(pos)
        return rec

    broker.execute_order.side_effect = _execute
    broker.fetch_available.return_value = 10000.0
    return broker


def _mock_sizer(quantity: float = 2.5) -> MagicMock:
    sizer = MagicMock()
    sizer.calculate.return_value = PositionSizeResult(
        quantity=quantity,
        risk_amount=10.0,
        position_value=250.0,
        kelly_applied=False,
        allocation_weight=0.8,
        size_factor=1.0,
        reason="test",
    )
    return sizer


def _mock_portfolio_risk(weights: dict[str, float] | None = None) -> MagicMock:
    pr = MagicMock()
    pr.get_allocation_weights.return_value = weights if weights is not None else {"test:1.0": 0.8}
    pr.check_correlation_gate.return_value = (True, "passed")
    return pr


def make_signal(**kwargs) -> TradingSignal:
    defaults = dict(
        strategy_id="test:1.0",
        symbol="BTC/USDT",
        timeframe="5m",
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
        stop_loss=95.0,
        take_profits=[110.0],
        reason="test signal",
        metadata={
            "ohlcv_df": pd.DataFrame(
                {"open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000.0]}
            ),
            "returns": pd.Series([0.01, -0.005, 0.02]),
        },
    )
    defaults.update(kwargs)
    return TradingSignal(**defaults)


def test_alert_only_mode_sends_notification_without_execution(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer()
    pr = _mock_portfolio_risk()
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)

    state = orchestrator.process_signal(make_signal())

    assert len(state.executions) == 0
    assert len(state.pending_orders) == 0
    assert len(notifier.signals) == 1
    assert len(state.positions) == 0


def test_semi_auto_mode_creates_pending_until_approved(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer(quantity=3.0)
    pr = _mock_portfolio_risk()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)
    control.set_mode(TradingMode.semi_auto)

    state = orchestrator.process_signal(make_signal())

    assert len(state.pending_orders) == 1
    assert len(state.executions) == 0
    assert len(notifier.pending) == 1

    updated = control.approve_pending(state.pending_orders[0].pending_id)

    assert len(updated.executions) == 1
    assert updated.pending_orders[0].state.value == "executed"
    assert len(updated.positions) == 1


def test_auto_mode_executes_immediately(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer(quantity=2.5)
    pr = _mock_portfolio_risk()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)
    control.set_mode(TradingMode.auto)

    state = orchestrator.process_signal(make_signal())

    assert len(state.executions) == 1
    assert len(state.positions) == 1
    assert state.positions[0].entry_price == 100.0
    # quantity from sizer
    assert notifier.executions[0].quantity == 2.5


def test_paused_runtime_does_not_create_pending_or_execution(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer()
    pr = _mock_portfolio_risk()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)
    control.set_mode(TradingMode.auto)
    control.pause()

    state = orchestrator.process_signal(make_signal())

    assert len(state.executions) == 0
    assert len(state.pending_orders) == 0
    assert any("paused" in message for message in notifier.messages)


def test_full_auto_uses_position_sizer(tmp_path):
    """full_auto mode calls position_sizer.calculate() and uses result.quantity."""
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer(quantity=2.5)
    pr = _mock_portfolio_risk({"test:1.0": 0.8})
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)
    control.set_mode(TradingMode.auto)

    signal = make_signal()
    state = orchestrator.process_signal(signal)

    # sizer was called
    sizer.calculate.assert_called_once()
    call_kwargs = sizer.calculate.call_args
    assert call_kwargs.kwargs.get("allocation_weight") == 0.8 or (
        len(call_kwargs.args) > 7 and call_kwargs.args[7] == 0.8
    )
    # order used sizer quantity
    assert len(state.executions) == 1
    assert notifier.executions[0].quantity == 2.5


def test_full_auto_missing_sizer_raises(tmp_path):
    """Constructing orchestrator with position_sizer=None raises ValueError on process_signal."""
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    pr = _mock_portfolio_risk()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, position_sizer=None, portfolio_risk=pr)
    control.set_mode(TradingMode.auto)

    import pytest
    with pytest.raises(ValueError, match="position_sizer"):
        orchestrator.process_signal(make_signal())


def test_full_auto_missing_portfolio_risk_raises(tmp_path):
    """Constructing orchestrator with portfolio_risk=None raises ValueError on process_signal."""
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, position_sizer=sizer, portfolio_risk=None)
    control.set_mode(TradingMode.auto)

    import pytest
    with pytest.raises(ValueError, match="portfolio_risk"):
        orchestrator.process_signal(make_signal())


def test_unregistered_strategy_blocked(tmp_path):
    """Strategy not in allocation_weights is blocked from entry."""
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = _mock_broker()
    sizer = _mock_sizer()
    pr = _mock_portfolio_risk(weights={})  # empty = no registered strategies
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker, sizer, pr)
    control.set_mode(TradingMode.auto)

    state = orchestrator.process_signal(make_signal())

    assert len(state.executions) == 0
    assert any("unregistered" in msg.lower() or "blocked" in msg.lower() for msg in notifier.messages)

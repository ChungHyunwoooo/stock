
from engine.application.trading import TradingControlService, TradingOrchestrator
from engine.core import SignalAction, TradeSide, TradingMode, TradingSignal
from engine.execution import PaperBroker
from engine.notifications import MemoryNotifier
from engine.core import JsonRuntimeStore

def make_signal() -> TradingSignal:
    return TradingSignal(
        strategy_id="test:1.0",
        symbol="BTC/USDT",
        timeframe="5m",
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
        stop_loss=95.0,
        take_profits=[110.0],
        reason="test signal",
    )

def test_alert_only_mode_sends_notification_without_execution(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    orchestrator = TradingOrchestrator(store, notifier, broker)

    state = orchestrator.process_signal(make_signal(), quantity=2.0)

    assert len(state.executions) == 0
    assert len(state.pending_orders) == 0
    assert len(notifier.signals) == 1
    assert len(state.positions) == 0

def test_semi_auto_mode_creates_pending_until_approved(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker)
    control.set_mode(TradingMode.semi_auto)

    state = orchestrator.process_signal(make_signal(), quantity=3.0)

    assert len(state.pending_orders) == 1
    assert state.pending_orders[0].quantity == 3.0
    assert len(state.executions) == 0
    assert len(notifier.pending) == 1

    updated = control.approve_pending(state.pending_orders[0].pending_id)

    assert len(updated.executions) == 1
    assert updated.pending_orders[0].state.value == "executed"
    assert len(updated.positions) == 1
    assert updated.positions[0].quantity == 3.0

def test_auto_mode_executes_immediately(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker)
    control.set_mode(TradingMode.auto)

    state = orchestrator.process_signal(make_signal(), quantity=1.5)

    assert len(state.executions) == 1
    assert len(state.positions) == 1
    assert state.positions[0].entry_price == 100.0
    assert notifier.executions[0].quantity == 1.5

def test_paused_runtime_does_not_create_pending_or_execution(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    control = TradingControlService(store, notifier, broker)
    orchestrator = TradingOrchestrator(store, notifier, broker)
    control.set_mode(TradingMode.auto)
    control.pause()

    state = orchestrator.process_signal(make_signal(), quantity=1.0)

    assert len(state.executions) == 0
    assert len(state.pending_orders) == 0
    assert any("paused" in message for message in notifier.messages)

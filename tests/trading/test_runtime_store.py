from __future__ import annotations

from engine.domain.trading import PendingOrder, SignalAction, TradeSide, TradingMode, TradingRuntimeState, TradingSignal
from engine.infrastructure.runtime import JsonRuntimeStore


def test_runtime_store_round_trip(tmp_path):
    path = tmp_path / "runtime.json"
    store = JsonRuntimeStore(path)
    state = TradingRuntimeState(mode=TradingMode.semi_auto)
    signal = TradingSignal(
        strategy_id="test:1.0",
        symbol="ETH/USDT",
        timeframe="1h",
        action=SignalAction.entry,
        side=TradeSide.short,
        entry_price=2500.0,
    )
    state.pending_orders.append(PendingOrder(pending_id="abc123", signal=signal, quantity=2.0))

    store.save(state)
    loaded = store.load()

    assert loaded.mode is TradingMode.semi_auto
    assert loaded.pending_orders[0].pending_id == "abc123"
    assert loaded.pending_orders[0].signal.symbol == "ETH/USDT"
    assert loaded.pending_orders[0].signal.side is TradeSide.short

from __future__ import annotations

from engine.application.trading.presenters import build_signal_presentation
from engine.domain.trading import SignalAction, TradeSide, TradingSignal


def test_signal_presentation_includes_trade_decision_fields():
    signal = TradingSignal(
        strategy_id="test:1.0",
        symbol="BTC/USDT",
        timeframe="15m",
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
        stop_loss=98.0,
        take_profits=[106.0],
        confidence=0.84,
        reason="breakout + volume",
        metadata={"market": "crypto_spot"},
    )

    presentation = build_signal_presentation(signal, mode_label="semi_auto")

    field_names = [field.name for field in presentation.fields]
    assert presentation.title == "Trading signal: BTC/USDT [15m]"
    assert "Risk %" in field_names
    assert "Reward %" in field_names
    assert "R/R" in field_names
    assert "Context" in field_names

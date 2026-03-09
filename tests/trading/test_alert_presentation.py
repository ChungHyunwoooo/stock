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
    assert "LONG" in presentation.title
    assert "BTC" in presentation.title
    assert "15m" in presentation.title
    assert "진입가" in field_names
    assert "손절가" in field_names
    assert "신뢰도" in field_names

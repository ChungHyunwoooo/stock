from __future__ import annotations

import pandas as pd

from engine.application.trading.charts import build_analysis_chart
from engine.application.trading.reports import AnalysisReport
from engine.domain.trading import SignalAction, TradeSide, TradingSignal


def _sample_frame() -> pd.DataFrame:
    index = pd.date_range('2026-03-01', periods=60, freq='15min', tz='UTC')
    base = pd.Series(range(60), index=index, dtype=float) + 100.0
    return pd.DataFrame(
        {
            'open': base,
            'high': base + 1.0,
            'low': base - 1.0,
            'close': base + 0.5,
            'volume': 1000.0,
        },
        index=index,
    )


def test_build_analysis_chart_uses_first_signal_as_overlay(monkeypatch):
    signal = TradingSignal(
        strategy_id='test:1.0',
        symbol='BTC/USDT',
        timeframe='15m',
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
        stop_loss=98.0,
        take_profits=[104.0],
    )
    report = AnalysisReport(
        symbol='BTC/USDT',
        exchange='binance',
        timeframe='15m',
        scanned_at='2026-03-06T00:00:00+00:00',
        last_price=100.0,
        price_change_pct=2.0,
        range_pct=5.0,
        volume_ratio=1.2,
        trend_bias='BULLISH',
        bars=60,
        high=105.0,
        low=95.0,
        signal_count=1,
        notes=[],
        signals=[signal],
    )
    captured = {}

    monkeypatch.setattr('engine.application.trading.charts._fetch_chart_frame', lambda *args, **kwargs: _sample_frame())

    def fake_render_chart(df, symbol, timeframe, exchange, overlay_signal=None):
        captured['symbol'] = symbol
        captured['timeframe'] = timeframe
        captured['exchange'] = exchange
        captured['overlay_signal'] = overlay_signal
        return b'chart-bytes'

    monkeypatch.setattr('engine.application.trading.charts._render_chart', fake_render_chart)

    result = build_analysis_chart(report)

    assert result == b'chart-bytes'
    assert captured['symbol'] == 'BTC/USDT'
    assert captured['timeframe'] == '15m'
    assert captured['exchange'] == 'binance'
    assert captured['overlay_signal'] is signal
    assert signal.metadata['exchange'] == 'binance'

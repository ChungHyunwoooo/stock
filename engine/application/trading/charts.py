"""Unified chart generation for all outputs (scan alerts, /analysis command).

Single source of truth: delegates to strategy-specific chart generation
from upbit_scanner.generate_chart() to ensure visual consistency.
"""
from __future__ import annotations

import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import talib

from engine.alerts.discord import Signal
from engine.application.trading.reports import AnalysisReport
from engine.data.base import get_provider
from engine.domain.trading.models import TradingSignal
from engine.schema import MarketType

logger = logging.getLogger(__name__)

_LOOKBACK = {
    '1m': pd.Timedelta(minutes=180),
    '5m': pd.Timedelta(hours=18),
    '15m': pd.Timedelta(days=2),
    '30m': pd.Timedelta(days=4),
    '1h': pd.Timedelta(days=7),
    '4h': pd.Timedelta(days=30),
    '1d': pd.Timedelta(days=180),
    '1w': pd.Timedelta(days=720),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_signal_chart(signal: TradingSignal) -> bytes | None:
    """Generate chart for a TradingSignal (used by /analysis single signal)."""
    try:
        exchange = str(signal.metadata.get('exchange', _exchange_for_symbol(signal.symbol)))
        df = _fetch_chart_frame(signal.symbol, signal.timeframe, exchange)
        if df.empty:
            return None
        return _generate_basic_chart(df, signal.symbol, signal.timeframe,
                                     str(signal.metadata.get('exchange', '')))
    except Exception as exc:
        logger.warning('Signal chart generation failed for %s: %s', signal.symbol, exc)
        return None


def build_analysis_chart(report: AnalysisReport) -> bytes | None:
    """Generate chart for an AnalysisReport.

    If the report has signals, use the top signal's strategy-specific chart.
    Otherwise, generate a basic candlestick chart.
    """
    try:
        df = _fetch_chart_frame(report.symbol, report.timeframe, report.exchange)
        if df.empty:
            return None

        if report.signals:
            top_signal = report.signals[0]
            if 'exchange' not in top_signal.metadata:
                top_signal.metadata['exchange'] = report.exchange
            return _generate_basic_chart(df, report.symbol, report.timeframe, report.exchange)
        else:
            return _generate_basic_chart(df, report.symbol, report.timeframe, report.exchange)
    except Exception as exc:
        logger.warning('Analysis chart generation failed for %s: %s', report.symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Signal type converter
# ---------------------------------------------------------------------------

def _to_alert_signal(signal: TradingSignal) -> Signal:
    """Convert domain TradingSignal to alerts Signal for chart generation."""
    return Signal(
        strategy=signal.strategy_id,
        symbol=signal.symbol,
        side=signal.side.value.upper(),
        entry=signal.entry_price,
        stop_loss=signal.stop_loss or signal.entry_price * 0.98,
        take_profits=list(signal.take_profits),
        timeframe=signal.timeframe,
        confidence=signal.confidence,
        reason=signal.reason,
        metadata=dict(signal.metadata),
    )



def _generate_basic_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    exchange: str,
) -> bytes:
    """Fallback chart when no signal exists (report-only)."""
    chart_df = df.tail(80).copy()
    chart_df.index = pd.DatetimeIndex(chart_df.index)
    close = chart_df["close"].values

    style = _chart_style()
    ap = []
    if len(chart_df) >= 20:
        ema20 = talib.EMA(close, timeperiod=20)
        ap.append(mpf.make_addplot(ema20, color='#FFD166', width=1.0))
    if len(chart_df) >= 50:
        ema50 = talib.EMA(close, timeperiod=50)
        ap.append(mpf.make_addplot(ema50, color='#06D6A0', width=1.0))

    ticker = symbol.replace("KRW-", "").replace("/USDT", "").replace("/KRW", "")
    fig, axes = mpf.plot(
        chart_df,
        type='candle',
        style=style,
        addplot=ap,
        volume=True,
        title=f"{ticker} [{timeframe}]",
        figsize=(12, 8),
        returnfig=True,
        panel_ratios=(3, 1),
    )
    fig.text(
        0.99, 0.01,
        f"{exchange} | {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ha='right', va='bottom', fontsize=7, color='#888888',
    )
    return _save_chart(fig)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _chart_style():
    mc = mpf.make_marketcolors(
        up='#26a69a', down='#ef5350',
        edge={'up': '#26a69a', 'down': '#ef5350'},
        wick={'up': '#26a69a', 'down': '#ef5350'},
        volume={'up': '#26a69a80', 'down': '#ef535080'},
    )
    return mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style='nightclouds',
        gridstyle=':',
        gridcolor='#333333',
    )


def _save_chart(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                facecolor='#1a1a2e', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _market_for_symbol(symbol: str) -> MarketType:
    normalized = symbol.upper()
    if '/' in normalized or normalized.startswith(('KRW-', 'BTC-', 'USDT-')):
        return MarketType.crypto_spot
    if normalized.isdigit():
        return MarketType.kr_stock
    return MarketType.us_stock


def _exchange_for_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    return 'upbit' if normalized.startswith('KRW-') else 'binance'


def _fetch_chart_frame(symbol: str, timeframe: str, exchange: str) -> pd.DataFrame:
    market = _market_for_symbol(symbol)
    provider = get_provider(market, exchange=exchange)
    end = pd.Timestamp.now(tz='UTC')
    start = end - _LOOKBACK.get(timeframe, pd.Timedelta(days=7))
    return provider.fetch_ohlcv(
        symbol,
        start.strftime('%Y-%m-%d %H:%M:%S'),
        end.strftime('%Y-%m-%d %H:%M:%S'),
        timeframe,
    )

"""S3: Momentum Scanner — 급등/급락 초기 포착 (1m/5m).

Detects rapid price movement with volume confirmation.
"""

from __future__ import annotations

import pandas as pd
import talib

from engine.alerts.discord import Signal


def scan_momentum(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    price_change_pct: float = 1.5,
    lookback_bars: int = 3,
    vol_mult: float = 2.0,
    rsi_max_long: float = 78.0,
    rsi_min_short: float = 22.0,
    sl_pct: float = 0.01,
    tp1_pct: float = 0.015,
    tp2_pct: float = 0.025,
    leverage: int = 3,
) -> Signal | None:
    """Detect momentum breakout on the latest bars.

    Conditions (LONG):
    - Price rose >= price_change_pct% in last lookback_bars bars
    - Average volume over those bars >= vol_mult × 20-bar average
    - RSI < rsi_max_long (not already overbought)
    - Last candle is bullish (confirmation)

    Mirror conditions for SHORT.
    """
    if len(df) < max(lookback_bars + 20, 30):
        return None

    close = df["close"]
    volume = df["volume"]

    # Price change over lookback window
    current = float(close.iloc[-1])
    past = float(close.iloc[-1 - lookback_bars])
    pct_change = (current - past) / past * 100

    # Volume surge over lookback window
    recent_vol_avg = float(volume.iloc[-lookback_bars:].mean())
    baseline_vol = float(volume.iloc[-lookback_bars - 20:-lookback_bars].mean())
    vol_ratio = recent_vol_avg / baseline_vol if baseline_vol > 0 else 0

    if vol_ratio < vol_mult:
        return None

    rsi = pd.Series(talib.RSI(close.values, timeperiod=14), index=df.index)
    last_rsi = float(rsi.iloc[-1])
    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    confidence = min(1.0, (abs(pct_change) / price_change_pct) * 0.5 + (vol_ratio / 10) * 0.5)

    # Momentum LONG
    if pct_change >= price_change_pct and last_rsi < rsi_max_long and is_bullish:
        return Signal(
            strategy="S3_MOMENTUM",
            symbol=symbol,
            side="LONG",
            entry=current,
            stop_loss=round(current * (1 - sl_pct), 6),
            take_profits=[round(current * (1 + tp1_pct), 6), round(current * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"{lookback_bars}봉 내 +{pct_change:.1f}% 급등, 거래량 {vol_ratio:.1f}x, RSI {last_rsi:.0f}",
        )

    # Momentum SHORT
    if pct_change <= -price_change_pct and last_rsi > rsi_min_short and is_bearish:
        return Signal(
            strategy="S3_MOMENTUM",
            symbol=symbol,
            side="SHORT",
            entry=current,
            stop_loss=round(current * (1 + sl_pct), 6),
            take_profits=[round(current * (1 - tp1_pct), 6), round(current * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"{lookback_bars}봉 내 {pct_change:.1f}% 급락, 거래량 {vol_ratio:.1f}x, RSI {last_rsi:.0f}",
        )

    return None

"""Scalping strategies for crypto futures (1m/5m timeframes).

S6: Volume Spike Scalp — 거래량 폭증 + 가격 돌파
S7: RSI Extreme Reversal — RSI 극단에서 반전 포착
"""

from __future__ import annotations

import pandas as pd
import talib

from engine.alerts.discord import Signal


def _vol_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume / rolling average volume."""
    avg = df["volume"].rolling(period).mean()
    return df["volume"] / avg


def _donchian(df: pd.DataFrame, period: int = 20) -> tuple[pd.Series, pd.Series]:
    """Donchian channel (highest high, lowest low)."""
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    return upper, lower


# ---------------------------------------------------------------------------
# S6: Volume Spike Scalp
# ---------------------------------------------------------------------------

def scan_volume_spike(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    vol_mult: float = 2.5,
    donchian_period: int = 20,
    sl_pct: float = 0.003,
    tp1_pct: float = 0.005,
    tp2_pct: float = 0.010,
    leverage: int = 5,
) -> Signal | None:
    """Detect volume spike breakout on the latest bar.

    Conditions:
    - Volume > vol_mult × 20-period average
    - Close above Donchian upper (breakout) → LONG
    - Close below Donchian lower (breakdown) → SHORT
    - RSI not in extreme opposite direction
    """
    if len(df) < donchian_period + 5:
        return None

    vr = _vol_ratio(df, 20)
    upper, lower = _donchian(df, donchian_period)
    rsi = pd.Series(talib.RSI(df["close"].values, timeperiod=14), index=df.index)

    last = df.iloc[-1]
    prev_upper = upper.iloc[-2]
    prev_lower = lower.iloc[-2]
    last_vr = vr.iloc[-1]
    last_rsi = rsi.iloc[-1]

    if last_vr < vol_mult:
        return None

    close = float(last["close"])

    # Breakout LONG
    if close > prev_upper and last_rsi < 78:
        return Signal(
            strategy="S6_VOLUME_SPIKE_SCALP",
            symbol=symbol,
            side="LONG",
            entry=close,
            stop_loss=round(close * (1 - sl_pct), 6),
            take_profits=[round(close * (1 + tp1_pct), 6), round(close * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=min(1.0, last_vr / 10),
            reason=f"거래량 {last_vr:.1f}x 폭증 + Donchian 상단 돌파. RSI {last_rsi:.0f}",
        )

    # Breakdown SHORT
    if close < prev_lower and last_rsi > 22:
        return Signal(
            strategy="S6_VOLUME_SPIKE_SCALP",
            symbol=symbol,
            side="SHORT",
            entry=close,
            stop_loss=round(close * (1 + sl_pct), 6),
            take_profits=[round(close * (1 - tp1_pct), 6), round(close * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=min(1.0, last_vr / 10),
            reason=f"거래량 {last_vr:.1f}x 폭증 + Donchian 하단 이탈. RSI {last_rsi:.0f}",
        )

    return None


# ---------------------------------------------------------------------------
# S7: RSI Extreme Reversal
# ---------------------------------------------------------------------------

def scan_rsi_extreme(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    sl_pct: float = 0.005,
    tp1_pct: float = 0.005,
    tp2_pct: float = 0.012,
    leverage: int = 3,
) -> Signal | None:
    """Detect RSI extreme reversal on the latest bars.

    Conditions:
    - RSI was below oversold (or above overbought) on prev bar
    - RSI is now crossing back (reversal underway)
    - Confirmation: current candle is reversal (close vs open)
    """
    if len(df) < 20:
        return None

    rsi = pd.Series(talib.RSI(df["close"].values, timeperiod=14), index=df.index)

    prev_rsi = rsi.iloc[-2]
    curr_rsi = rsi.iloc[-1]
    last = df.iloc[-1]
    close = float(last["close"])
    is_bullish_candle = last["close"] > last["open"]
    is_bearish_candle = last["close"] < last["open"]

    # Oversold bounce → LONG
    if prev_rsi < rsi_oversold and curr_rsi > prev_rsi and is_bullish_candle:
        return Signal(
            strategy="S7_RSI_EXTREME",
            symbol=symbol,
            side="LONG",
            entry=close,
            stop_loss=round(close * (1 - sl_pct), 6),
            take_profits=[round(close * (1 + tp1_pct), 6), round(close * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=0.6 + (rsi_oversold - prev_rsi) / 100,
            reason=f"RSI {prev_rsi:.0f}→{curr_rsi:.0f} 과매도 반전 + 양봉 확인",
        )

    # Overbought rejection → SHORT
    if prev_rsi > rsi_overbought and curr_rsi < prev_rsi and is_bearish_candle:
        return Signal(
            strategy="S7_RSI_EXTREME",
            symbol=symbol,
            side="SHORT",
            entry=close,
            stop_loss=round(close * (1 + sl_pct), 6),
            take_profits=[round(close * (1 - tp1_pct), 6), round(close * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=0.6 + (prev_rsi - rsi_overbought) / 100,
            reason=f"RSI {prev_rsi:.0f}→{curr_rsi:.0f} 과매수 반전 + 음봉 확인",
        )

    return None

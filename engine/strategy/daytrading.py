"""Daytrading strategies for crypto futures (5m timeframe).

S8: EMA Cross — EMA 9/21 크로스오버
S9: BB Squeeze — 볼린저 밴드 스퀴즈 돌파
S10: Key Level Break — 24시간 고점/저점 돌파
S11: Candle Surge — 급등/급락 감지
"""

from __future__ import annotations

import pandas as pd
import talib

from engine.alerts.discord import Signal


# ---------------------------------------------------------------------------
# S8: EMA Cross
# ---------------------------------------------------------------------------

def scan_ema_cross(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    sl_pct: float = 0.008,
    tp1_pct: float = 0.012,
    tp2_pct: float = 0.020,
    leverage: int = 3,
) -> Signal | None:
    """Detect EMA 9/21 crossover with candle confirmation.

    Conditions (LONG):
    - Previous bar: EMA9 <= EMA21
    - Current bar: EMA9 > EMA21 (golden cross)
    - Current candle is bullish (close > open)

    Mirror conditions for SHORT (death cross + bearish candle).
    """
    if len(df) < 30:
        return None

    close = df["close"]
    ema9 = pd.Series(talib.EMA(close.values, timeperiod=9), index=df.index)
    ema21 = pd.Series(talib.EMA(close.values, timeperiod=21), index=df.index)

    prev_ema9 = float(ema9.iloc[-2])
    curr_ema9 = float(ema9.iloc[-1])
    prev_ema21 = float(ema21.iloc[-2])
    curr_ema21 = float(ema21.iloc[-1])

    last = df.iloc[-1]
    entry = float(last["close"])
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    spread = abs(curr_ema9 - curr_ema21) / curr_ema21 if curr_ema21 > 0 else 0
    confidence = min(1.0, 0.6 + spread * 10)

    # Golden cross → LONG
    if prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21 and is_bullish:
        return Signal(
            strategy="S8_EMA_CROSS",
            symbol=symbol,
            side="LONG",
            entry=entry,
            stop_loss=round(entry * (1 - sl_pct), 6),
            take_profits=[round(entry * (1 + tp1_pct), 6), round(entry * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason="EMA9/21 골든크로스 + 양봉 확인",
        )

    # Death cross → SHORT
    if prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21 and is_bearish:
        return Signal(
            strategy="S8_EMA_CROSS",
            symbol=symbol,
            side="SHORT",
            entry=entry,
            stop_loss=round(entry * (1 + sl_pct), 6),
            take_profits=[round(entry * (1 - tp1_pct), 6), round(entry * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason="EMA9/21 데드크로스 + 음봉 확인",
        )

    return None


# ---------------------------------------------------------------------------
# S9: BB Squeeze
# ---------------------------------------------------------------------------

def scan_bb_squeeze(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    sl_pct: float = 0.010,
    tp1_pct: float = 0.015,
    tp2_pct: float = 0.025,
    leverage: int = 3,
) -> Signal | None:
    """Detect Bollinger Band squeeze breakout.

    Conditions:
    - Bandwidth was at minimum (squeeze) and is now expanding (>= 1.5x min)
    - Previous bar bandwidth was near the minimum (within 10%)
    - Direction: close > middle → LONG, close < middle → SHORT
    """
    if len(df) < 40:
        return None

    close = df["close"]
    upper, middle, lower = talib.BBANDS(close.values, timeperiod=20, nbdevup=2, nbdevdn=2)

    upper = pd.Series(upper, index=df.index)
    middle = pd.Series(middle, index=df.index)
    lower = pd.Series(lower, index=df.index)

    bandwidth = (upper - lower) / middle
    bandwidth_min = float(bandwidth.iloc[-20:].min())

    curr_bw = float(bandwidth.iloc[-1])
    prev_bw = float(bandwidth.iloc[-2])

    # Squeeze expanding: current BW > 1.5x min AND prev BW was near min (within 10%)
    if bandwidth_min <= 0:
        return None

    expanding = curr_bw > bandwidth_min * 1.5
    prev_near_min = prev_bw <= bandwidth_min * 1.1

    if not (expanding and prev_near_min):
        return None

    entry = float(close.iloc[-1])
    curr_middle = float(middle.iloc[-1])
    expansion_ratio = curr_bw / bandwidth_min if bandwidth_min > 0 else 1.0
    confidence = min(1.0, 0.65 + (expansion_ratio - 1.5) * 0.1)

    # Direction based on close vs middle band
    if entry > curr_middle:
        return Signal(
            strategy="S9_BB_SQUEEZE",
            symbol=symbol,
            side="LONG",
            entry=entry,
            stop_loss=round(entry * (1 - sl_pct), 6),
            take_profits=[round(entry * (1 + tp1_pct), 6), round(entry * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"BB 스퀴즈 상방 돌파 (밴드폭 {expansion_ratio:.1f}x 확장)",
        )

    if entry < curr_middle:
        return Signal(
            strategy="S9_BB_SQUEEZE",
            symbol=symbol,
            side="SHORT",
            entry=entry,
            stop_loss=round(entry * (1 + sl_pct), 6),
            take_profits=[round(entry * (1 - tp1_pct), 6), round(entry * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"BB 스퀴즈 하방 돌파 (밴드폭 {expansion_ratio:.1f}x 확장)",
        )

    return None


# ---------------------------------------------------------------------------
# S10: Key Level Break
# ---------------------------------------------------------------------------

def scan_key_level_break(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    lookback_bars: int = 288,
    vol_mult: float = 1.5,
    sl_pct: float = 0.005,
    tp1_pct: float = 0.010,
    tp2_pct: float = 0.020,
    leverage: int = 3,
) -> Signal | None:
    """Detect 24-hour key level breakout with volume confirmation.

    Conditions (LONG):
    - Close breaks above the previous 24h high (288 5m bars, excluding current)
    - Volume > vol_mult × 20-bar average

    Mirror conditions for SHORT.
    """
    if len(df) < 300:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # 24h high/low excluding current bar
    prev_24h_high = float(high.iloc[-lookback_bars - 1:-1].max())
    prev_24h_low = float(low.iloc[-lookback_bars - 1:-1].min())

    curr_close = float(close.iloc[-1])

    # Volume confirmation
    curr_vol = float(volume.iloc[-1])
    avg_vol = float(volume.iloc[-21:-1].mean())
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

    if vol_ratio < vol_mult:
        return None

    confidence = min(1.0, 0.6 + (vol_ratio - vol_mult) * 0.05)

    # Breakout LONG
    if curr_close > prev_24h_high:
        return Signal(
            strategy="S10_KEY_LEVEL",
            symbol=symbol,
            side="LONG",
            entry=curr_close,
            stop_loss=round(curr_close * (1 - sl_pct), 6),
            take_profits=[round(curr_close * (1 + tp1_pct), 6), round(curr_close * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"24시간 고점 ${prev_24h_high:,.4f} 돌파, 거래량 {vol_ratio:.1f}x",
        )

    # Breakdown SHORT
    if curr_close < prev_24h_low:
        return Signal(
            strategy="S10_KEY_LEVEL",
            symbol=symbol,
            side="SHORT",
            entry=curr_close,
            stop_loss=round(curr_close * (1 + sl_pct), 6),
            take_profits=[round(curr_close * (1 - tp1_pct), 6), round(curr_close * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"24시간 저점 ${prev_24h_low:,.4f} 이탈, 거래량 {vol_ratio:.1f}x",
        )

    return None


# ---------------------------------------------------------------------------
# S11: Candle Surge
# ---------------------------------------------------------------------------

def scan_candle_surge(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    move_pct: float = 0.01,
    vol_mult: float = 2.0,
    sl_pct: float = 0.005,
    tp1_pct: float = 0.008,
    tp2_pct: float = 0.015,
    leverage: int = 2,
) -> Signal | None:
    """Detect single-candle surge with volume confirmation.

    Conditions:
    - abs((close - open) / open) >= move_pct (1% single-candle move)
    - Volume > vol_mult × 20-bar average
    - Direction: bullish candle → LONG, bearish → SHORT
    """
    if len(df) < 25:
        return None

    last = df.iloc[-1]
    open_price = float(last["open"])
    close_price = float(last["close"])
    curr_vol = float(last["volume"])

    candle_move = (close_price - open_price) / open_price if open_price > 0 else 0

    if abs(candle_move) < move_pct:
        return None

    volume = df["volume"]
    avg_vol = float(volume.iloc[-21:-1].mean())
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

    if vol_ratio < vol_mult:
        return None

    confidence = min(1.0, (abs(candle_move) / move_pct) * 0.4 + (vol_ratio / 10) * 0.6)

    # Bullish surge → LONG
    if candle_move > 0:
        return Signal(
            strategy="S11_CANDLE_SURGE",
            symbol=symbol,
            side="LONG",
            entry=close_price,
            stop_loss=round(close_price * (1 - sl_pct), 6),
            take_profits=[round(close_price * (1 + tp1_pct), 6), round(close_price * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"단봉 +{candle_move * 100:.1f}% 급등, 거래량 {vol_ratio:.1f}x",
        )

    # Bearish surge → SHORT
    if candle_move < 0:
        return Signal(
            strategy="S11_CANDLE_SURGE",
            symbol=symbol,
            side="SHORT",
            entry=close_price,
            stop_loss=round(close_price * (1 + sl_pct), 6),
            take_profits=[round(close_price * (1 - tp1_pct), 6), round(close_price * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe=timeframe,
            confidence=confidence,
            reason=f"단봉 {candle_move * 100:.1f}% 급락, 거래량 {vol_ratio:.1f}x",
        )

    return None

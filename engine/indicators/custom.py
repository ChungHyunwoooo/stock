"""Custom composite indicators not available in ta-lib.

Implements 세력계단 (Force Staircase) and 수박지표 (Watermelon) from 주식단테.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _valuewhen(condition: pd.Series, value: pd.Series) -> pd.Series:
    """Capture value when condition is True, hold until next True.

    Equivalent to TradingView's valuewhen(condition, source, 0).
    """
    result = pd.Series(np.nan, index=value.index, dtype=float)
    result[condition] = value[condition]
    return result.ffill()


def _ichimoku_senkou_span2(
    high: pd.Series,
    low: pd.Series,
    period: int = 52,
    displacement: int = 26,
) -> pd.Series:
    """Ichimoku Senkou Span 2 (Leading Span B).

    (52-period highest high + 52-period lowest low) / 2, displaced forward.
    """
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return ((highest + lowest) / 2).shift(displacement)


# ---------------------------------------------------------------------------
# STAIRCASE (세력계단)
# ---------------------------------------------------------------------------


def staircase_indicator(
    df: pd.DataFrame,
    ema_period: int = 26,
    std_period: int = 26,
    std_mult: float = 2.5,
    shift_period: int = 25,
    step_length: int = 7,
    support_period: int = 112,
    long_period: int = 448,
    escape_pct: float = 8.0,
    ready_pct: float = 8.0,
    start_pct: float = 5.0,
    short_gap_pct: float = 8.0,
    gap_224_pct: float = 8.0,
    cloud_gap_pct: float = 8.0,
) -> dict[str, pd.Series]:
    """세력계단 (Force Staircase) composite indicator.

    EMA + StdDev based staircase support line that visualises accumulation
    zones created by institutional players.

    Returns dict with keys: staircase, proximity1, proximity2.
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    # --- Core staircase line ---
    # a = shift(ema(c, period) + mult * StdDev(typical, period), shift)
    ema_short = c.ewm(span=ema_period, adjust=False).mean()
    typical = (c + h + lo) / 3
    std = typical.rolling(std_period).std()
    a = (ema_short + std_mult * std).shift(shift_period)

    # b = HIGHEST(a, step_length)
    b = a.rolling(step_length).max()

    # x = VALUEWHEN(a breaks above previous highest)
    x = _valuewhen(a > b.shift(1), a)

    # y = VALUEWHEN(a drops from previous bar, capture x)  →  step function
    y = _valuewhen(a < a.shift(1), x)

    # EMA lines
    ema_sup = c.ewm(span=support_period, adjust=False).mean()
    ema_lng = c.ewm(span=long_period, adjust=False).mean()
    ema_224 = c.ewm(span=224, adjust=False).mean()

    # Main staircase: show raw 'a' when price escapes, otherwise hold step 'y'
    escape_mask = (c * (100 + escape_pct) / 100 >= a) & (ema_sup < ema_lng)
    staircase_line = y.copy()
    staircase_line[escape_mask] = a[escape_mask]

    # --- Ichimoku cloud ---
    senkou2 = _ichimoku_senkou_span2(h, lo)

    # --- 224 EMA band filter ---
    ema_band = (ema_224 * (100 + gap_224_pct) / 100 >= c) & (
        ema_224 * (100 - gap_224_pct) / 100 <= c
    )

    # --- Common conditions ---
    downtrend = ema_sup < ema_lng
    near_staircase_upper = a * (100 + short_gap_pct) / 100 > c

    # --- 근접1 (proximity1): price below 112 EMA, near staircase ---
    z1 = (ema_sup > c) & (senkou2 * (100 + cloud_gap_pct) / 100 > c)
    prox1_mask = (
        (c * (100 + ready_pct) / 100 >= a)
        & near_staircase_upper
        & downtrend
        & z1
        & ema_band
    )
    proximity1 = pd.Series(0.0, index=df.index)
    proximity1[prox1_mask] = 1.0

    # --- 근접2 (proximity2): price above 112 EMA, near staircase ---
    z2 = (ema_sup < c) & (senkou2 * (100 + cloud_gap_pct) / 100 > c)
    prox2_mask = (
        (c * (100 + start_pct) / 100 >= a)
        & near_staircase_upper
        & downtrend
        & z2
        & ema_band
    )
    proximity2 = pd.Series(0.0, index=df.index)
    proximity2[prox2_mask] = 1.0

    return {
        "staircase": staircase_line,
        "proximity1": proximity1,
        "proximity2": proximity2,
    }


# ---------------------------------------------------------------------------
# WATERMELON (수박지표)
# ---------------------------------------------------------------------------


def watermelon_indicator(
    df: pd.DataFrame,
    ema_period: int = 26,
    std_period: int = 26,
    std_mult: float = 2.5,
    shift_period: int = 25,
    scale1: float = 7.5,
    scale2: float = 4.5,
    support_period: int = 112,
    mid_period: int = 224,
    long_period: int = 448,
    ema_gap_pct: float = 1.0,
    short_gap_pct: float = 15.0,
    fortress_period: int = 5,
) -> dict[str, pd.Series]:
    """수박지표 (Watermelon) composite indicator.

    EMA + StdDev based accumulation visualiser.  When the red bar (melon)
    fills the blue bar (shell), accumulation is nearly complete.

    Returns dict with keys: shell, melon.
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    # n1 = shift(ema + mult * std, shift) / scale1
    ema_short = c.ewm(span=ema_period, adjust=False).mean()
    typical = (c + h + lo) / 3
    std = typical.rolling(std_period).std()
    n1 = (ema_short + std_mult * std).shift(shift_period) / scale1

    # EMA lines
    ema_sup = c.ewm(span=support_period, adjust=False).mean()
    ema_mid = c.ewm(span=mid_period, adjust=False).mean()
    ema_lng = c.ewm(span=long_period, adjust=False).mean()
    ema_fort = c.ewm(span=fortress_period, adjust=False).mean()

    # 가 condition (EMA alignment + gap filters)
    ga = (
        (ema_sup * (100 + ema_gap_pct) / 100 < ema_mid)
        & (ema_mid * (100 + ema_gap_pct) / 100 < ema_lng)
        & (ema_mid * (100 + short_gap_pct) / 100 >= c)
        & (ema_sup < ema_fort)
    )

    # Active only when price is above 112 EMA
    active = ema_sup <= c

    # Shell (껍질): if(가, n1, 0) → if(ema112 > c, 0, result)
    shell = pd.Series(0.0, index=df.index)
    shell[ga & active] = n1[ga & active]

    # Watermelon (수박): val=high/scale1; if(n1<val, high/scale2, val)
    val = h / scale1
    inner = val.copy()
    inner[n1 < val] = (h / scale2)[n1 < val]

    melon = pd.Series(0.0, index=df.index)
    melon[ga & active] = inner[ga & active]

    return {
        "shell": shell,
        "melon": melon,
    }

"""세력계단 (Force Staircase) — EMA+StdDev 기반 세력 매집 구간 시각화."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _valuewhen(condition: pd.Series, value: pd.Series) -> pd.Series:
    """조건이 True일 때 값을 캡처하고, 다음 True까지 유지."""
    result = pd.Series(np.nan, index=value.index, dtype=float)
    result[condition] = value[condition]
    return result.ffill()


def _ichimoku_senkou_span2(
    high: pd.Series, low: pd.Series, period: int = 52, displacement: int = 26,
) -> pd.Series:
    """Ichimoku Senkou Span 2 (Leading Span B)."""
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return ((highest + lowest) / 2).shift(displacement)


def staircase(
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
    """세력계단 지표 계산.

    Returns:
        dict with keys: staircase, proximity1, proximity2
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    ema_short = c.ewm(span=ema_period, adjust=False).mean()
    typical = (c + h + lo) / 3
    std = typical.rolling(std_period).std()
    a = (ema_short + std_mult * std).shift(shift_period)

    b = a.rolling(step_length).max()
    x = _valuewhen(a > b.shift(1), a)
    y = _valuewhen(a < a.shift(1), x)

    ema_sup = c.ewm(span=support_period, adjust=False).mean()
    ema_lng = c.ewm(span=long_period, adjust=False).mean()
    ema_224 = c.ewm(span=224, adjust=False).mean()

    escape_mask = (c * (100 + escape_pct) / 100 >= a) & (ema_sup < ema_lng)
    staircase_line = y.copy()
    staircase_line[escape_mask] = a[escape_mask]

    senkou2 = _ichimoku_senkou_span2(h, lo)

    ema_band = (ema_224 * (100 + gap_224_pct) / 100 >= c) & (
        ema_224 * (100 - gap_224_pct) / 100 <= c
    )

    downtrend = ema_sup < ema_lng
    near_staircase_upper = a * (100 + short_gap_pct) / 100 > c

    z1 = (ema_sup > c) & (senkou2 * (100 + cloud_gap_pct) / 100 > c)
    prox1_mask = (
        (c * (100 + ready_pct) / 100 >= a)
        & near_staircase_upper & downtrend & z1 & ema_band
    )
    proximity1 = pd.Series(0.0, index=df.index)
    proximity1[prox1_mask] = 1.0

    z2 = (ema_sup < c) & (senkou2 * (100 + cloud_gap_pct) / 100 > c)
    prox2_mask = (
        (c * (100 + start_pct) / 100 >= a)
        & near_staircase_upper & downtrend & z2 & ema_band
    )
    proximity2 = pd.Series(0.0, index=df.index)
    proximity2[prox2_mask] = 1.0

    return {"staircase": staircase_line, "proximity1": proximity1, "proximity2": proximity2}


# registry 호환 래퍼
staircase_indicator = staircase


def is_near_staircase(df: pd.DataFrame) -> bool:
    """현재 가격이 세력계단 근접 구간인지."""
    result = staircase(df)
    return float(result["proximity1"].iloc[-1]) > 0 or float(result["proximity2"].iloc[-1]) > 0


def describe() -> dict:
    return {
        "name": "세력계단",
        "name_en": "Force Staircase",
        "category": "custom",
        "params": {
            "ema_period": 26, "std_period": 26, "std_mult": 2.5,
            "shift_period": 25, "step_length": 7,
            "support_period": 112, "long_period": 448,
        },
        "outputs": ["staircase", "proximity1", "proximity2"],
        "interpretation": "EMA+StdDev 기반 세력 매집 구간. proximity1/2가 1이면 매집 근접.",
    }

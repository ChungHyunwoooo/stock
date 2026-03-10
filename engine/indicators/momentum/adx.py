"""ADX(평균방향성지수) + 방향성 이동 인디케이터."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def adx(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """ADX 계산."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    values = talib.ADX(h, l, c, timeperiod=period)
    return SingleResult.from_array(values)


def plus_di(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """+DI 계산."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    values = talib.PLUS_DI(h, l, c, timeperiod=period)
    return SingleResult.from_array(values)


def minus_di(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """-DI 계산."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    values = talib.MINUS_DI(h, l, c, timeperiod=period)
    return SingleResult.from_array(values)


def is_trending(
    high: Array, low: Array, close: Array, period: int = 14, threshold: float = 25
) -> bool:
    """ADX가 임계값 이상이면 추세 존재 (True)."""
    result = adx(high, low, close, period)
    return not np.isnan(result.current) and result.current >= threshold


def trend_direction(high: Array, low: Array, close: Array, period: int = 14) -> str:
    """추세 방향 반환. +DI > -DI이면 'BULL', 아니면 'BEAR'."""
    pdi = plus_di(high, low, close, period)
    mdi = minus_di(high, low, close, period)
    if np.isnan(pdi.current) or np.isnan(mdi.current):
        return "BEAR"
    return "BULL" if pdi.current > mdi.current else "BEAR"


def describe() -> dict:
    """ADX 인디케이터 메타데이터."""
    return {
        "name": "ADX",
        "full_name": "Average Directional Movement Index",
        "range": [0, 100],
        "trend_threshold": 25,
        "default_period": 14,
        "outputs": ["ADX", "+DI", "-DI"],
        "description": "25 이상 추세 존재, +DI > -DI면 상승 추세",
    }

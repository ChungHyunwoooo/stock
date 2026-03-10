"""Williams %R 인디케이터 — 과매수/과매도 감지."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def willr(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """Williams %R 계산. 범위: [-100, 0]."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    values = talib.WILLR(h, l, c, timeperiod=period)
    return SingleResult.from_array(values)


def is_oversold(
    high: Array, low: Array, close: Array, period: int = 14, threshold: float = -80
) -> bool:
    """현재 %R이 임계값 이하이면 True (과매도)."""
    result = willr(high, low, close, period)
    return not np.isnan(result.current) and result.current <= threshold


def is_overbought(
    high: Array, low: Array, close: Array, period: int = 14, threshold: float = -20
) -> bool:
    """현재 %R이 임계값 이상이면 True (과매수)."""
    result = willr(high, low, close, period)
    return not np.isnan(result.current) and result.current >= threshold


def describe() -> dict:
    """Williams %R 인디케이터 메타데이터."""
    return {
        "name": "WILLR",
        "full_name": "Williams %R",
        "range": [-100, 0],
        "oversold": -80,
        "overbought": -20,
        "default_period": 14,
        "description": "-80 이하 과매도, -20 이상 과매수",
    }

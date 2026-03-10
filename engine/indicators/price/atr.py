"""ATR(Average True Range) 및 파생 지표."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def atr(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """평균 실제 범위(ATR)."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    result = talib.ATR(h, l, c, timeperiod=period)
    return SingleResult.from_array(result)


def natr(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """정규화 ATR (%) = ATR / close * 100."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    result = talib.NATR(h, l, c, timeperiod=period)
    return SingleResult.from_array(result)


def true_range(high: Array, low: Array, close: Array) -> SingleResult:
    """실제 범위(True Range) 단일 값 배열."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    result = talib.TRANGE(h, l, c)
    return SingleResult.from_array(result)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Average True Range",
        "functions": ["atr", "natr", "true_range"],
        "inputs": ["high", "low", "close"],
        "defaults": {"period": 14},
        "outputs": ["SingleResult"],
    }

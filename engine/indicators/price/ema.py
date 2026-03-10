"""EMA/SMA/WMA/DEMA/TEMA 이동평균 지표 모음."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def ema(close: Array, period: int = 21) -> SingleResult:
    """지수이동평균(EMA)."""
    c = _to_numpy(close)
    result = talib.EMA(c, timeperiod=period)
    return SingleResult.from_array(result)


def sma(close: Array, period: int = 20) -> SingleResult:
    """단순이동평균(SMA)."""
    c = _to_numpy(close)
    result = talib.SMA(c, timeperiod=period)
    return SingleResult.from_array(result)


def wma(close: Array, period: int = 20) -> SingleResult:
    """가중이동평균(WMA)."""
    c = _to_numpy(close)
    result = talib.WMA(c, timeperiod=period)
    return SingleResult.from_array(result)


def dema(close: Array, period: int = 21) -> SingleResult:
    """이중지수이동평균(DEMA)."""
    c = _to_numpy(close)
    result = talib.DEMA(c, timeperiod=period)
    return SingleResult.from_array(result)


def tema(close: Array, period: int = 21) -> SingleResult:
    """삼중지수이동평균(TEMA)."""
    c = _to_numpy(close)
    result = talib.TEMA(c, timeperiod=period)
    return SingleResult.from_array(result)


def is_above(close: Array, period: int = 21) -> bool:
    """현재 가격이 EMA 위에 있는지 여부."""
    c = _to_numpy(close)
    e = talib.EMA(c, timeperiod=period)
    if np.isnan(e[-1]):
        return False
    return bool(c[-1] > e[-1])


def is_golden_cross(close: Array, fast: int = 20, slow: int = 50) -> bool:
    """골든 크로스: fast EMA가 slow EMA를 상향 돌파."""
    c = _to_numpy(close)
    fast_ema = talib.EMA(c, timeperiod=fast)
    slow_ema = talib.EMA(c, timeperiod=slow)
    if np.isnan(fast_ema[-1]) or np.isnan(slow_ema[-1]):
        return False
    if np.isnan(fast_ema[-2]) or np.isnan(slow_ema[-2]):
        return False
    return bool(fast_ema[-2] <= slow_ema[-2] and fast_ema[-1] > slow_ema[-1])


def is_death_cross(close: Array, fast: int = 20, slow: int = 50) -> bool:
    """데스 크로스: fast EMA가 slow EMA를 하향 돌파."""
    c = _to_numpy(close)
    fast_ema = talib.EMA(c, timeperiod=fast)
    slow_ema = talib.EMA(c, timeperiod=slow)
    if np.isnan(fast_ema[-1]) or np.isnan(slow_ema[-1]):
        return False
    if np.isnan(fast_ema[-2]) or np.isnan(slow_ema[-2]):
        return False
    return bool(fast_ema[-2] >= slow_ema[-2] and fast_ema[-1] < slow_ema[-1])


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Moving Averages",
        "functions": ["ema", "sma", "wma", "dema", "tema", "is_above", "is_golden_cross", "is_death_cross"],
        "inputs": ["close"],
        "defaults": {"ema_period": 21, "sma_period": 20, "wma_period": 20, "dema_period": 21, "tema_period": 21},
        "outputs": ["SingleResult"],
    }

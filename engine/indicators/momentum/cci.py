"""CCI(상품채널지수) 인디케이터 — 과매수/과매도 감지."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def cci(high: Array, low: Array, close: Array, period: int = 14) -> SingleResult:
    """CCI 계산."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    values = talib.CCI(h, l, c, timeperiod=period)
    return SingleResult.from_array(values)


def is_oversold(
    high: Array, low: Array, close: Array, period: int = 14, threshold: float = -100
) -> bool:
    """현재 CCI가 임계값 이하이면 True (과매도)."""
    result = cci(high, low, close, period)
    return not np.isnan(result.current) and result.current <= threshold


def is_overbought(
    high: Array, low: Array, close: Array, period: int = 14, threshold: float = 100
) -> bool:
    """현재 CCI가 임계값 이상이면 True (과매수)."""
    result = cci(high, low, close, period)
    return not np.isnan(result.current) and result.current >= threshold


def describe() -> dict:
    """CCI 인디케이터 메타데이터."""
    return {
        "name": "CCI",
        "full_name": "Commodity Channel Index",
        "oversold": -100,
        "overbought": 100,
        "default_period": 14,
        "description": "-100 이하 과매도, +100 이상 과매수",
    }

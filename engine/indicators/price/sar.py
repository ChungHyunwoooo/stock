"""포물선 SAR(Parabolic Stop and Reverse) 지표."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def sar(high: Array, low: Array, acceleration: float = 0.02, maximum: float = 0.2) -> SingleResult:
    """포물선 SAR 값 배열."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    result = talib.SAR(h, l, acceleration=acceleration, maximum=maximum)
    return SingleResult.from_array(result)


def trend(high: Array, low: Array, close: Array, acceleration: float = 0.02, maximum: float = 0.2) -> str:
    """현재 추세 방향: 'LONG' (가격 > SAR) 또는 'SHORT' (가격 < SAR)."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    sar_vals = talib.SAR(h, l, acceleration=acceleration, maximum=maximum)
    if np.isnan(sar_vals[-1]) or np.isnan(c[-1]):
        return "SHORT"
    return "LONG" if c[-1] > sar_vals[-1] else "SHORT"


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Parabolic SAR",
        "functions": ["sar", "trend"],
        "inputs": ["high", "low"],
        "defaults": {"acceleration": 0.02, "maximum": 0.2},
        "outputs": ["SingleResult", "str"],
    }

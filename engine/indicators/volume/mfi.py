"""Money Flow Index (MFI) — 거래량 가중 RSI형 모멘텀 인디케이터."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def mfi(high: Array, low: Array, close: Array, volume: Array, period: int = 14) -> SingleResult:
    """MFI 계산."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    v = _to_numpy(volume)
    result = talib.MFI(h, l, c, v, timeperiod=period)
    return SingleResult.from_array(result)


def is_oversold(
    high: Array, low: Array, close: Array, volume: Array,
    period: int = 14, threshold: float = 20,
) -> bool:
    """현재 MFI가 과매도 임계값 이하인지 판단."""
    result = mfi(high, low, close, volume, period=period)
    current = result.current
    if np.isnan(current):
        return False
    return current <= threshold


def is_overbought(
    high: Array, low: Array, close: Array, volume: Array,
    period: int = 14, threshold: float = 80,
) -> bool:
    """현재 MFI가 과매수 임계값 이상인지 판단."""
    result = mfi(high, low, close, volume, period=period)
    current = result.current
    if np.isnan(current):
        return False
    return current >= threshold


def describe() -> dict:
    return {
        "name": "MFI",
        "full_name": "Money Flow Index",
        "inputs": ["high", "low", "close", "volume"],
        "outputs": ["values"],
        "params": {"period": 14},
        "description": "거래량 가중 RSI. 과매수(80+) / 과매도(20-) 판단에 사용.",
    }

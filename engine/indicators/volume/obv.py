"""On Balance Volume (OBV) — 거래량 누적 추세 인디케이터."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def obv(close: Array, volume: Array) -> SingleResult:
    """OBV 계산."""
    c = _to_numpy(close)
    v = _to_numpy(volume)
    result = talib.OBV(c, v)
    return SingleResult.from_array(result)


def trend(close: Array, volume: Array, period: int = 20) -> str:
    """OBV 추세 판단. OBV > SMA(OBV)이면 'UP', 아니면 'DOWN'."""
    result = obv(close, volume)
    vals = result.values
    if len(vals) < period:
        return "DOWN"
    sma = np.nanmean(vals[-period:])
    current = result.current
    if np.isnan(current) or np.isnan(sma):
        return "DOWN"
    return "UP" if current > sma else "DOWN"


def describe() -> dict:
    return {
        "name": "OBV",
        "full_name": "On Balance Volume",
        "inputs": ["close", "volume"],
        "outputs": ["values"],
        "params": {"period": 20},
        "description": "거래량 누적 추세 지표. 상승 시 거래량 추가, 하락 시 차감.",
    }

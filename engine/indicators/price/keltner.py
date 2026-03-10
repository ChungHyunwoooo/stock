"""켈트너 채널(Keltner Channel) 지표."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, BandResult, _to_numpy


def keltner(
    high: Array,
    low: Array,
    close: Array,
    ema_period: int = 20,
    atr_period: int = 10,
    atr_mult: float = 2.0,
) -> BandResult:
    """켈트너 채널: middle=EMA, upper=EMA+mult*ATR, lower=EMA-mult*ATR."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)

    middle = talib.EMA(c, timeperiod=ema_period)
    atr_vals = talib.ATR(h, l, c, timeperiod=atr_period)

    upper = middle + atr_mult * atr_vals
    lower = middle - atr_mult * atr_vals

    return BandResult.from_arrays(upper, middle, lower)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Keltner Channel",
        "functions": ["keltner"],
        "inputs": ["high", "low", "close"],
        "defaults": {"ema_period": 20, "atr_period": 10, "atr_mult": 2.0},
        "outputs": ["BandResult"],
    }

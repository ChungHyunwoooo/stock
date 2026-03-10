"""이동평균 엔벨로프(Moving Average Envelope) 지표."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, BandResult, _to_numpy


def envelope(close: Array, period: int = 20, pct: float = 2.5) -> BandResult:
    """MA 엔벨로프: middle=SMA, upper=SMA*(1+pct/100), lower=SMA*(1-pct/100)."""
    c = _to_numpy(close)
    middle = talib.SMA(c, timeperiod=period)
    factor = pct / 100.0
    upper = middle * (1 + factor)
    lower = middle * (1 - factor)
    return BandResult.from_arrays(upper, middle, lower)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Moving Average Envelope",
        "functions": ["envelope"],
        "inputs": ["close"],
        "defaults": {"period": 20, "pct": 2.5},
        "outputs": ["BandResult"],
    }

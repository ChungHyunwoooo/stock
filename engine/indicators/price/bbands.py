"""볼린저 밴드(Bollinger Bands) 및 파생 지표."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, BandResult, SingleResult, _to_numpy


def bbands(close: Array, period: int = 20, nbdev: float = 2.0) -> BandResult:
    """볼린저 밴드 (upper, middle, lower)."""
    c = _to_numpy(close)
    upper, middle, lower = talib.BBANDS(c, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev, matype=0)
    return BandResult.from_arrays(upper, middle, lower)


def bandwidth(close: Array, period: int = 20, nbdev: float = 2.0) -> SingleResult:
    """밴드폭: (upper - lower) / middle."""
    c = _to_numpy(close)
    upper, middle, lower = talib.BBANDS(c, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev, matype=0)
    bw = np.where(middle != 0, (upper - lower) / middle, np.nan)
    return SingleResult.from_array(bw)


def pct_b(close: Array, period: int = 20, nbdev: float = 2.0) -> SingleResult:
    """%B: (close - lower) / (upper - lower)."""
    c = _to_numpy(close)
    upper, middle, lower = talib.BBANDS(c, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev, matype=0)
    band_width = upper - lower
    pctb = np.where(band_width != 0, (c - lower) / band_width, np.nan)
    return SingleResult.from_array(pctb)


def is_squeeze(close: Array, period: int = 20, nbdev: float = 2.0, threshold: float = 0.04) -> bool:
    """밴드폭이 threshold 미만이면 스퀴즈 상태."""
    bw = bandwidth(close, period=period, nbdev=nbdev)
    if np.isnan(bw.current):
        return False
    return bool(bw.current < threshold)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Bollinger Bands",
        "functions": ["bbands", "bandwidth", "pct_b", "is_squeeze"],
        "inputs": ["close"],
        "defaults": {"period": 20, "nbdev": 2.0, "squeeze_threshold": 0.04},
        "outputs": ["BandResult", "SingleResult", "SingleResult", "bool"],
    }

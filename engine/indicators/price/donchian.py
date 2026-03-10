"""돈치안 채널(Donchian Channel) 지표 (numpy rolling 구현)."""

from __future__ import annotations

import numpy as np

from engine.indicators.base import Array, BandResult, _to_numpy


def donchian(high: Array, low: Array, period: int = 20) -> BandResult:
    """돈치안 채널: upper=최고가, lower=최저가, middle=평균."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    n = len(h)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(period - 1, n):
        upper[i] = np.max(h[i - period + 1 : i + 1])
        lower[i] = np.min(l[i - period + 1 : i + 1])

    middle = (upper + lower) / 2

    return BandResult.from_arrays(upper, middle, lower)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Donchian Channel",
        "functions": ["donchian"],
        "inputs": ["high", "low"],
        "defaults": {"period": 20},
        "outputs": ["BandResult"],
        "note": "talib 미사용, numpy rolling으로 구현",
    }

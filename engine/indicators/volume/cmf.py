"""Chaikin Money Flow (CMF) — 차이킨 머니 플로우 인디케이터."""

from __future__ import annotations

import numpy as np

from engine.indicators.base import Array, SingleResult, _to_numpy


def _money_flow_volume(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Money Flow Volume 계산: MFV = ((close - low) - (high - close)) / (high - low) * volume."""
    hl_range = high - low
    # 고가 == 저가인 봉 처리 (0 나눔 방지)
    safe_range = np.where(hl_range == 0, np.nan, hl_range)
    clv = ((close - low) - (high - close)) / safe_range
    clv = np.nan_to_num(clv, nan=0.0)
    return clv * volume


def cmf(high: Array, low: Array, close: Array, volume: Array, period: int = 20) -> SingleResult:
    """CMF 계산: SUM(MFV, period) / SUM(volume, period)."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    v = _to_numpy(volume)

    mfv = _money_flow_volume(h, l, c, v)
    n = len(mfv)
    result = np.full(n, np.nan)

    for i in range(period - 1, n):
        vol_sum = np.sum(v[i - period + 1: i + 1])
        if vol_sum == 0:
            result[i] = 0.0
        else:
            result[i] = np.sum(mfv[i - period + 1: i + 1]) / vol_sum

    return SingleResult.from_array(result)


def is_bullish(high: Array, low: Array, close: Array, volume: Array, period: int = 20) -> bool:
    """현재 CMF > 0이면 매집(bullish) 신호."""
    result = cmf(high, low, close, volume, period=period)
    current = result.current
    if np.isnan(current):
        return False
    return current > 0


def describe() -> dict:
    return {
        "name": "CMF",
        "full_name": "Chaikin Money Flow",
        "inputs": ["high", "low", "close", "volume"],
        "outputs": ["values"],
        "params": {"period": 20},
        "description": "차이킨 머니 플로우. +이면 매집, -이면 분산 압력.",
    }

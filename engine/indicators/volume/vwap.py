"""Volume Weighted Average Price (VWAP) — 거래량 가중 평균 가격 인디케이터."""

from __future__ import annotations

import numpy as np

from engine.indicators.base import Array, SingleResult, _to_numpy


def _typical_price(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Typical price = (high + low + close) / 3."""
    return (high + low + close) / 3.0


def vwap(high: Array, low: Array, close: Array, volume: Array) -> SingleResult:
    """VWAP 계산: cumsum(typical_price * volume) / cumsum(volume)."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    v = _to_numpy(volume)

    tp = _typical_price(h, l, c)
    cum_tpv = np.cumsum(tp * v)
    cum_vol = np.cumsum(v)

    # 누적 거래량이 0인 구간 처리
    safe_vol = np.where(cum_vol == 0, np.nan, cum_vol)
    result = cum_tpv / safe_vol
    return SingleResult.from_array(result)


def is_above(close: Array, high: Array, low: Array, volume: Array) -> bool:
    """현재 종가가 VWAP 위에 있으면 True."""
    c = _to_numpy(close)
    result = vwap(high, low, close, volume)
    vwap_val = result.current
    if len(c) == 0 or np.isnan(vwap_val):
        return False
    current_close = float(c[-1])
    if np.isnan(current_close):
        return False
    return current_close > vwap_val


def describe() -> dict:
    return {
        "name": "VWAP",
        "full_name": "Volume Weighted Average Price",
        "inputs": ["high", "low", "close", "volume"],
        "outputs": ["values"],
        "params": {},
        "description": "거래량 가중 평균 가격. 종가 > VWAP이면 매수 우위.",
    }

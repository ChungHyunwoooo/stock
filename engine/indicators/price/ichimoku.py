"""이치모쿠 클라우드(Ichimoku Cloud) 지표 (pandas rolling 구현)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators.base import Array, _to_numpy


def ichimoku(
    high: Array,
    low: Array,
    close: Array,
    tenkan: int = 9,
    kijun: int = 26,
    senkou: int = 52,
) -> dict[str, np.ndarray]:
    """이치모쿠 구름 계산.

    Returns:
        tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span
    """
    h = pd.Series(_to_numpy(high))
    l = pd.Series(_to_numpy(low))
    c = pd.Series(_to_numpy(close))

    tenkan_sen = (h.rolling(tenkan).max() + l.rolling(tenkan).min()) / 2
    kijun_sen = (h.rolling(kijun).max() + l.rolling(kijun).min()) / 2

    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    senkou_span_b = ((h.rolling(senkou).max() + l.rolling(senkou).min()) / 2).shift(kijun)
    chikou_span = c.shift(-kijun)

    return {
        "tenkan_sen": tenkan_sen.values,
        "kijun_sen": kijun_sen.values,
        "senkou_span_a": senkou_span_a.values,
        "senkou_span_b": senkou_span_b.values,
        "chikou_span": chikou_span.values,
    }


def _get_cloud_bounds(high: Array, low: Array, close: Array) -> tuple[float, float]:
    """현재봉 기준 구름 상단/하단 반환."""
    result = ichimoku(high, low, close)
    span_a = result["senkou_span_a"]
    span_b = result["senkou_span_b"]

    # 현재 위치에서 유효한 구름값 탐색 (shift로 앞에 채워진 구간)
    idx = -1
    while idx >= -len(span_a) and (np.isnan(span_a[idx]) or np.isnan(span_b[idx])):
        idx -= 1

    if np.isnan(span_a[idx]) or np.isnan(span_b[idx]):
        return float("nan"), float("nan")

    cloud_top = max(float(span_a[idx]), float(span_b[idx]))
    cloud_bottom = min(float(span_a[idx]), float(span_b[idx]))
    return cloud_top, cloud_bottom


def is_above_cloud(high: Array, low: Array, close: Array) -> bool:
    """현재 가격이 구름 위에 있는지 여부."""
    c = _to_numpy(close)
    cloud_top, cloud_bottom = _get_cloud_bounds(high, low, close)
    if np.isnan(cloud_top):
        return False
    return bool(c[-1] > cloud_top)


def is_below_cloud(high: Array, low: Array, close: Array) -> bool:
    """현재 가격이 구름 아래에 있는지 여부."""
    c = _to_numpy(close)
    cloud_top, cloud_bottom = _get_cloud_bounds(high, low, close)
    if np.isnan(cloud_bottom):
        return False
    return bool(c[-1] < cloud_bottom)


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Ichimoku Cloud",
        "functions": ["ichimoku", "is_above_cloud", "is_below_cloud"],
        "inputs": ["high", "low", "close"],
        "defaults": {"tenkan": 9, "kijun": 26, "senkou": 52},
        "outputs": ["dict[str, np.ndarray]", "bool", "bool"],
        "note": "talib 미사용, pandas rolling으로 구현",
    }

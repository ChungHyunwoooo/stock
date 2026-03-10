"""스토캐스틱 오실레이터 — 과매수/과매도 및 스토캐스틱 RSI."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, DualResult, _to_numpy


def stochastic(
    high: Array,
    low: Array,
    close: Array,
    fastk: int = 5,
    slowk: int = 3,
    slowd: int = 3,
) -> DualResult:
    """Stochastic Oscillator — slowK, slowD 반환."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    sk, sd = talib.STOCH(h, l, c, fastk_period=fastk, slowk_period=slowk, slowd_period=slowd)
    return DualResult.from_arrays(sk, sd)


def stochastic_rsi(
    close: Array,
    period: int = 14,
    fastk: int = 5,
    fastd: int = 3,
) -> DualResult:
    """Stochastic RSI — fastK, fastD 반환."""
    c = _to_numpy(close)
    fk, fd = talib.STOCHRSI(c, timeperiod=period, fastk_period=fastk, fastd_period=fastd)
    return DualResult.from_arrays(fk, fd)


def is_oversold(high: Array, low: Array, close: Array, threshold: float = 20) -> bool:
    """현재 slowK가 임계값 이하이면 True (과매도)."""
    result = stochastic(high, low, close)
    return not np.isnan(result.current_line) and result.current_line <= threshold


def is_overbought(high: Array, low: Array, close: Array, threshold: float = 80) -> bool:
    """현재 slowK가 임계값 이상이면 True (과매수)."""
    result = stochastic(high, low, close)
    return not np.isnan(result.current_line) and result.current_line >= threshold


def describe() -> dict:
    """Stochastic 인디케이터 메타데이터."""
    return {
        "name": "Stochastic",
        "full_name": "Stochastic Oscillator",
        "range": [0, 100],
        "oversold": 20,
        "overbought": 80,
        "default_fastk": 5,
        "default_slowk": 3,
        "default_slowd": 3,
        "outputs": ["slowK", "slowD"],
        "description": "20 이하 과매도, 80 이상 과매수",
    }

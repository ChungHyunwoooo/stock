"""MACD(이동평균수렴확산) 인디케이터 — 추세 전환 감지."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, TripleResult, _to_numpy


def macd(close: Array, fast: int = 12, slow: int = 26, signal: int = 9) -> TripleResult:
    """MACD line, signal line, histogram 계산."""
    c = _to_numpy(close)
    line, sig, hist = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return TripleResult.from_arrays(line, sig, hist)


def is_bullish_cross(close: Array, fast: int = 12, slow: int = 26, signal: int = 9) -> bool:
    """MACD line이 signal line을 상향 돌파하면 True."""
    c = _to_numpy(close)
    line, sig, _ = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    valid = ~(np.isnan(line) | np.isnan(sig))
    idx = np.where(valid)[0]
    if len(idx) < 2:
        return False
    prev, curr = idx[-2], idx[-1]
    return bool(line[prev] <= sig[prev] and line[curr] > sig[curr])


def is_bearish_cross(close: Array, fast: int = 12, slow: int = 26, signal: int = 9) -> bool:
    """MACD line이 signal line을 하향 돌파하면 True."""
    c = _to_numpy(close)
    line, sig, _ = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    valid = ~(np.isnan(line) | np.isnan(sig))
    idx = np.where(valid)[0]
    if len(idx) < 2:
        return False
    prev, curr = idx[-2], idx[-1]
    return bool(line[prev] >= sig[prev] and line[curr] < sig[curr])


def describe() -> dict:
    """MACD 인디케이터 메타데이터."""
    return {
        "name": "MACD",
        "full_name": "Moving Average Convergence Divergence",
        "default_fast": 12,
        "default_slow": 26,
        "default_signal": 9,
        "outputs": ["line", "signal", "histogram"],
        "description": "추세 전환 및 모멘텀 측정",
    }

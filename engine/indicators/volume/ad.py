"""Accumulation/Distribution Line (A/D) — 누적/분산 라인 인디케이터."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def ad(high: Array, low: Array, close: Array, volume: Array) -> SingleResult:
    """A/D Line 계산 (talib.AD 사용)."""
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    v = _to_numpy(volume)
    result = talib.AD(h, l, c, v)
    return SingleResult.from_array(result)


def describe() -> dict:
    return {
        "name": "AD",
        "full_name": "Accumulation/Distribution Line",
        "inputs": ["high", "low", "close", "volume"],
        "outputs": ["values"],
        "params": {},
        "description": "누적/분산 라인. 매집(상승) vs 분산(하락) 압력을 측정.",
    }

"""피봇 포인트(Pivot Points) 지표 (클래식 방식)."""

from __future__ import annotations

import numpy as np

from engine.indicators.base import Array, _to_numpy


def pivot(high: Array, low: Array, close: Array) -> dict[str, float]:
    """클래식 피봇 포인트 계산.

    Returns:
        pp, r1, r2, r3, s1, s2, s3
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)

    # 직전 봉(마지막 완성 봉) 기준
    ph = float(h[-2]) if len(h) >= 2 else float(h[-1])
    pl = float(l[-2]) if len(l) >= 2 else float(l[-1])
    pc = float(c[-2]) if len(c) >= 2 else float(c[-1])

    pp = (ph + pl + pc) / 3

    r1 = 2 * pp - pl
    s1 = 2 * pp - ph

    r2 = pp + (ph - pl)
    s2 = pp - (ph - pl)

    r3 = ph + 2 * (pp - pl)
    s3 = pl - 2 * (ph - pp)

    return {
        "pp": pp,
        "r1": r1,
        "r2": r2,
        "r3": r3,
        "s1": s1,
        "s2": s2,
        "s3": s3,
    }


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Pivot Points",
        "functions": ["pivot"],
        "inputs": ["high", "low", "close"],
        "defaults": {},
        "outputs": ["dict[str, float]"],
        "note": "클래식 피봇 공식, 직전 봉 기준 계산",
    }

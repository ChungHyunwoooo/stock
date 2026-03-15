"""피보나치 되돌림(Fibonacci Retracement) 지표.

스윙 고점/저점을 자동 감지하여 되돌림 레벨을 계산.
의존성: numpy
"""

from __future__ import annotations

import numpy as np

from engine.indicators.base import Array, _to_numpy


# 표준 피보나치 되돌림 비율
RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)

# 피보나치 익스텐션 비율
EXT_RATIOS = (1.272, 1.618, 2.0, 2.618)


def _find_swing_high(high: np.ndarray, order: int = 5) -> tuple[int, float]:
    """lookback 내 스윙 고점(인덱스, 값) 반환."""
    for i in range(len(high) - 1 - order, order - 1, -1):
        if all(high[i] >= high[i - j] for j in range(1, order + 1)) and \
           all(high[i] >= high[i + j] for j in range(1, min(order + 1, len(high) - i))):
            return i, float(high[i])
    # 폴백: 단순 최고점
    idx = int(np.argmax(high))
    return idx, float(high[idx])


def _find_swing_low(low: np.ndarray, order: int = 5) -> tuple[int, float]:
    """lookback 내 스윙 저점(인덱스, 값) 반환."""
    for i in range(len(low) - 1 - order, order - 1, -1):
        if all(low[i] <= low[i - j] for j in range(1, order + 1)) and \
           all(low[i] <= low[i + j] for j in range(1, min(order + 1, len(low) - i))):
            return i, float(low[i])
    # 폴백: 단순 최저점
    idx = int(np.argmin(low))
    return idx, float(low[idx])


def fibonacci_retracement(
    high: Array,
    low: Array,
    close: Array,
    lookback: int = 120,
    swing_order: int = 5,
    ratios: tuple[float, ...] = RATIOS,
) -> dict[str, float | dict[float, float] | str]:
    """피보나치 되돌림 레벨 계산.

    Args:
        high: 고가 배열
        low: 저가 배열
        close: 종가 배열
        lookback: 스윙 탐색 범위 (봉 수)
        swing_order: 스윙 판정에 쓸 좌우 봉 수
        ratios: 되돌림 비율 튜플

    Returns:
        {
            trend: "up" | "down",
            swing_high: float,
            swing_low: float,
            levels: {ratio: price, ...},
            current_ratio: float,       # 현재가의 되돌림 비율 (0~1)
            nearest_level: float,       # 가장 가까운 피보 레벨 가격
            nearest_ratio: float,       # 가장 가까운 피보 비율
        }
    """
    h = _to_numpy(high)[-lookback:]
    l = _to_numpy(low)[-lookback:]
    c = _to_numpy(close)[-lookback:]

    nan_result: dict[str, float | dict[float, float] | str] = {
        "trend": "unknown",
        "swing_high": float("nan"),
        "swing_low": float("nan"),
        "levels": {},
        "current_ratio": float("nan"),
        "nearest_level": float("nan"),
        "nearest_ratio": float("nan"),
    }

    if len(c) < swing_order * 2 + 1:
        return nan_result

    hi_idx, hi_val = _find_swing_high(h, swing_order)
    lo_idx, lo_val = _find_swing_low(l, swing_order)

    diff = hi_val - lo_val
    if diff <= 0:
        return nan_result

    # 추세 판별: 고점이 저점보다 나중이면 상승 추세
    trend = "up" if hi_idx > lo_idx else "down"

    # 되돌림 레벨 계산
    # 상승 추세: 고점에서 되돌림 (고점 → 저점 방향)
    # 하락 추세: 저점에서 되돌림 (저점 → 고점 방향)
    levels: dict[float, float] = {}
    if trend == "up":
        for r in ratios:
            levels[r] = hi_val - diff * r
    else:
        for r in ratios:
            levels[r] = lo_val + diff * r

    # 현재가 되돌림 비율
    curr = float(c[-1])
    if trend == "up":
        current_ratio = (hi_val - curr) / diff
    else:
        current_ratio = (curr - lo_val) / diff
    current_ratio = max(0.0, min(current_ratio, 2.0))

    # 가장 가까운 피보 레벨
    nearest_ratio = min(ratios, key=lambda r: abs(levels[r] - curr))
    nearest_level = levels[nearest_ratio]

    return {
        "trend": trend,
        "swing_high": hi_val,
        "swing_low": lo_val,
        "levels": levels,
        "current_ratio": round(current_ratio, 4),
        "nearest_level": nearest_level,
        "nearest_ratio": nearest_ratio,
    }


def fibonacci_extension(
    high: Array,
    low: Array,
    close: Array,
    lookback: int = 120,
    swing_order: int = 5,
    ext_ratios: tuple[float, ...] = EXT_RATIOS,
) -> dict[str, float | dict[float, float] | str]:
    """피보나치 익스텐션 레벨 계산.

    추세 지속 시 목표가 산출용.

    Returns:
        {
            trend: "up" | "down",
            swing_high: float,
            swing_low: float,
            extensions: {ratio: price, ...},
        }
    """
    h = _to_numpy(high)[-lookback:]
    l = _to_numpy(low)[-lookback:]
    c = _to_numpy(close)[-lookback:]

    nan_result: dict[str, float | dict[float, float] | str] = {
        "trend": "unknown",
        "swing_high": float("nan"),
        "swing_low": float("nan"),
        "extensions": {},
    }

    if len(c) < swing_order * 2 + 1:
        return nan_result

    hi_idx, hi_val = _find_swing_high(h, swing_order)
    lo_idx, lo_val = _find_swing_low(l, swing_order)

    diff = hi_val - lo_val
    if diff <= 0:
        return nan_result

    trend = "up" if hi_idx > lo_idx else "down"

    extensions: dict[float, float] = {}
    if trend == "up":
        for r in ext_ratios:
            extensions[r] = lo_val + diff * r
    else:
        for r in ext_ratios:
            extensions[r] = hi_val - diff * r

    return {
        "trend": trend,
        "swing_high": hi_val,
        "swing_low": lo_val,
        "extensions": extensions,
    }


def describe() -> dict:
    """지표 메타정보 반환."""
    return {
        "name": "Fibonacci Retracement & Extension",
        "functions": ["fibonacci_retracement", "fibonacci_extension"],
        "inputs": ["high", "low", "close"],
        "defaults": {"lookback": 120, "swing_order": 5},
        "outputs": ["dict"],
        "note": "스윙 자동 감지 → 되돌림/익스텐션 레벨 계산, 추세 방향별 해석",
    }

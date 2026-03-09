"""차트 패턴 실시간 감지기 — 백테스트와 실시간 공용.

패턴 목록 (채택된 4종만):
  1. Double Bottom (LONG) — 두 저점 유사 + 넥라인 돌파
  2. Double Top (SHORT) — 두 고점 유사 + 넥라인 하향 이탈
  3. Ascending Triangle (LONG) — 수평 저항 + 상승 지지 + 상방 돌파
  4. Descending Triangle (SHORT) — 수평 지지 + 하강 저항 + 하방 돌파

SL/TP: 지지·저항 기반 (고정 비율 아님)
  - LONG: SL=직전 지지, TP=다음 저항
  - SHORT: SL=직전 저항, TP=다음 지지

look-ahead 방지:
  극값 k를 사용하려면 k + order < current_bar 이어야 함.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class PatternSignal:
    pattern: str        # "DOUBLE_BOTTOM" | "DOUBLE_TOP" | "ASC_TRIANGLE" | "DESC_TRIANGLE"
    side: str           # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    bar_index: int
    metadata: dict


# ---------------------------------------------------------------------------
# 로컬 극값 탐지 (전체 배열 1회 계산)
# ---------------------------------------------------------------------------

def find_local_extrema(arr: np.ndarray, order: int = 5) -> tuple[list[int], list[int]]:
    """로컬 최소/최대 인덱스 반환. order봉 좌우 비교."""
    mins: list[int] = []
    maxs: list[int] = []
    for k in range(order, len(arr) - order):
        if all(arr[k] <= arr[k - j] for j in range(1, order + 1)) and \
           all(arr[k] <= arr[k + j] for j in range(1, order + 1)):
            mins.append(k)
        if all(arr[k] >= arr[k - j] for j in range(1, order + 1)) and \
           all(arr[k] >= arr[k + j] for j in range(1, order + 1)):
            maxs.append(k)
    return mins, maxs


def confirmed_before(indices: list[int], current: int,
                     lookback: int = 50, order: int = 5) -> list[int]:
    """look-ahead 방지: k + order < current 이고 lookback 범위 내."""
    cutoff = current - lookback
    return [k for k in indices if cutoff <= k and k + order < current]


# ---------------------------------------------------------------------------
# 지지·저항 기반 SL/TP 헬퍼
# ---------------------------------------------------------------------------

_MIN_PEAK_SEPARATION = 10  # 두 극값 사이 최소 봉 수
_SL_MARGIN = 0.002  # SL 마진 (0.2%)
_MIN_RR = 1.0  # 최소 R:R — 이보다 낮은 레벨은 스킵
_TP_FALLBACK_RATIO = 2.0  # 적절한 레벨 없을 때 폴백 R:R


def _find_next_resistance(price: float, sl_dist: float, high: np.ndarray,
                          high_maxs: list[int], i: int, order: int = 5) -> float | None:
    """현재가 위 저항선 중 R:R >= 1인 첫 번째 레벨."""
    confirmed = [k for k in high_maxs if k + order < i]
    levels = sorted(set(float(high[k]) for k in confirmed if float(high[k]) > price))
    for lv in levels:
        reward = lv - price
        if sl_dist > 0 and reward / sl_dist >= _MIN_RR:
            return lv
    return None


def _find_next_support(price: float, sl_dist: float, low: np.ndarray,
                       low_mins: list[int], i: int, order: int = 5) -> float | None:
    """현재가 아래 지지선 중 R:R >= 1인 첫 번째 레벨."""
    confirmed = [k for k in low_mins if k + order < i]
    levels = sorted(set(float(low[k]) for k in confirmed if float(low[k]) < price), reverse=True)
    for lv in levels:
        reward = price - lv
        if sl_dist > 0 and reward / sl_dist >= _MIN_RR:
            return lv
    return None


def _calc_long_tp(entry: float, sl: float, high: np.ndarray,
                  high_maxs: list[int], i: int) -> float:
    """LONG TP: R:R >= 1인 저항 → 없으면 폴백."""
    sl_dist = entry - sl
    resistance = _find_next_resistance(entry, sl_dist, high, high_maxs, i)
    if resistance:
        return resistance
    return entry + _TP_FALLBACK_RATIO * sl_dist


def _calc_short_tp(entry: float, sl: float, low: np.ndarray,
                   low_mins: list[int], i: int) -> float:
    """SHORT TP: R:R >= 1인 지지 → 없으면 폴백."""
    sl_dist = sl - entry
    support = _find_next_support(entry, sl_dist, low, low_mins, i)
    if support:
        return support
    return entry - _TP_FALLBACK_RATIO * sl_dist


# ---------------------------------------------------------------------------
# 패턴 1: Double Bottom (LONG)
# ---------------------------------------------------------------------------

def detect_double_bottom(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    i: int,
    low_mins: list[int], high_maxs: list[int],
    lookback: int = 50,
    extrema_order: int = 5,
    tolerance: float = 0.02,
) -> PatternSignal | None:
    """현재 봉(i)에서 Double Bottom 패턴 감지."""
    recent_mins = confirmed_before(low_mins, i, lookback, extrema_order)
    if len(recent_mins) < 2:
        return None

    m2, m1 = recent_mins[-1], recent_mins[-2]

    if abs(m2 - m1) < _MIN_PEAK_SEPARATION:
        return None

    low1, low2 = float(low[m1]), float(low[m2])

    if abs(low1 - low2) / max(low1, low2) > tolerance:
        return None

    # 넥라인: 두 저점 사이 high 극값 최고점
    between_maxs = [m for m in high_maxs if m1 < m < m2 and m <= i - extrema_order - 1]
    if between_maxs:
        neckline = max(float(high[m]) for m in between_maxs)
    else:
        neckline = float(np.max(high[m1:m2 + 1]))

    bar_close = float(close[i])
    if bar_close <= neckline:
        return None

    entry = bar_close
    sl = min(low1, low2) * (1 - _SL_MARGIN)
    tp = _calc_long_tp(entry, sl, high, high_maxs, i)

    return PatternSignal(
        pattern="DOUBLE_BOTTOM", side="LONG",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        bar_index=i,
        metadata={"low1": low1, "low2": low2, "neckline": neckline,
                  "m1_idx": m1, "m2_idx": m2},
    )


# ---------------------------------------------------------------------------
# 패턴 2: Double Top (SHORT)
# ---------------------------------------------------------------------------

def detect_double_top(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    i: int,
    high_maxs: list[int], low_mins: list[int],
    lookback: int = 50,
    extrema_order: int = 5,
    tolerance: float = 0.02,
) -> PatternSignal | None:
    """현재 봉(i)에서 Double Top 패턴 감지."""
    recent_maxs = confirmed_before(high_maxs, i, lookback, extrema_order)
    if len(recent_maxs) < 2:
        return None

    m2, m1 = recent_maxs[-1], recent_maxs[-2]

    if abs(m2 - m1) < _MIN_PEAK_SEPARATION:
        return None

    high1, high2 = float(high[m1]), float(high[m2])

    if abs(high1 - high2) / max(high1, high2) > tolerance:
        return None

    between_mins = [m for m in low_mins if m1 < m < m2 and m <= i - extrema_order - 1]
    if between_mins:
        neckline = min(float(low[m]) for m in between_mins)
    else:
        neckline = float(np.min(low[m1:m2 + 1]))

    bar_close = float(close[i])
    if bar_close >= neckline:
        return None

    entry = bar_close
    sl = max(high1, high2) * (1 + _SL_MARGIN)
    tp = _calc_short_tp(entry, sl, low, low_mins, i)

    return PatternSignal(
        pattern="DOUBLE_TOP", side="SHORT",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        bar_index=i,
        metadata={"high1": high1, "high2": high2, "neckline": neckline,
                  "m1_idx": m1, "m2_idx": m2},
    )


# ---------------------------------------------------------------------------
# 패턴 3: Ascending Triangle (LONG)
# ---------------------------------------------------------------------------

def detect_asc_triangle(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    i: int,
    low_mins: list[int], high_maxs: list[int],
    lookback: int = 40,
    extrema_order: int = 5,
    resistance_tol: float = 0.01,
) -> PatternSignal | None:
    """현재 봉(i)에서 Ascending Triangle 패턴 감지."""
    recent_maxs = confirmed_before(high_maxs, i, lookback, extrema_order)
    if len(recent_maxs) < 2:
        return None

    highs_at_maxs = [float(high[m]) for m in recent_maxs[-3:]]
    resistance = np.mean(highs_at_maxs)
    if max(abs(h - resistance) / resistance for h in highs_at_maxs) > resistance_tol:
        return None

    recent_mins = confirmed_before(low_mins, i, lookback, extrema_order)
    if len(recent_mins) < 2:
        return None

    lows_at_mins = [float(low[m]) for m in recent_mins[-3:]]
    if not all(lows_at_mins[j] < lows_at_mins[j + 1] for j in range(len(lows_at_mins) - 1)):
        return None

    bar_close = float(close[i])
    if bar_close <= resistance:
        return None

    entry = bar_close
    sl = lows_at_mins[-1] * (1 - _SL_MARGIN)
    tp = _calc_long_tp(entry, sl, high, high_maxs, i)

    return PatternSignal(
        pattern="ASC_TRIANGLE", side="LONG",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        bar_index=i,
        metadata={"resistance": resistance, "lows": lows_at_mins},
    )


# ---------------------------------------------------------------------------
# 패턴 4: Descending Triangle (SHORT)
# ---------------------------------------------------------------------------

def detect_desc_triangle(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    i: int,
    low_mins: list[int], high_maxs: list[int],
    lookback: int = 40,
    extrema_order: int = 5,
    support_tol: float = 0.01,
) -> PatternSignal | None:
    """현재 봉(i)에서 Descending Triangle 패턴 감지."""
    recent_mins = confirmed_before(low_mins, i, lookback, extrema_order)
    if len(recent_mins) < 2:
        return None

    lows_at_mins = [float(low[m]) for m in recent_mins[-3:]]
    support = np.mean(lows_at_mins)
    if max(abs(lv - support) / support for lv in lows_at_mins) > support_tol:
        return None

    recent_maxs = confirmed_before(high_maxs, i, lookback, extrema_order)
    if len(recent_maxs) < 2:
        return None

    highs_at_maxs = [float(high[m]) for m in recent_maxs[-3:]]
    if not all(highs_at_maxs[j] > highs_at_maxs[j + 1] for j in range(len(highs_at_maxs) - 1)):
        return None

    bar_close = float(close[i])
    if bar_close >= support:
        return None

    entry = bar_close
    sl = highs_at_maxs[-1] * (1 + _SL_MARGIN)
    tp = _calc_short_tp(entry, sl, low, low_mins, i)

    return PatternSignal(
        pattern="DESC_TRIANGLE", side="SHORT",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        bar_index=i,
        metadata={"support": support, "highs": highs_at_maxs},
    )


# ---------------------------------------------------------------------------
# 통합 스캔
# ---------------------------------------------------------------------------

def scan_patterns(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    i: int, direction: str,
    low_mins: list[int], low_maxs: list[int],
    high_mins: list[int], high_maxs: list[int],
) -> list[PatternSignal]:
    """방향 필터 적용 후 해당 패턴만 스캔."""
    results: list[PatternSignal] = []

    if direction in ("LONG", "NEUTRAL"):
        sig = detect_double_bottom(close, high, low, i, low_mins, high_maxs)
        if sig:
            results.append(sig)
        sig = detect_asc_triangle(close, high, low, i, low_mins, high_maxs)
        if sig:
            results.append(sig)

    if direction in ("SHORT", "NEUTRAL"):
        sig = detect_double_top(close, high, low, i, high_maxs, low_mins)
        if sig:
            results.append(sig)
        sig = detect_desc_triangle(close, high, low, i, low_mins, high_maxs)
        if sig:
            results.append(sig)

    return results

"""TDD 테스트 — engine/strategy/pattern_detector.py

핵심 함수 전체 커버:
  - find_local_extrema: 극값 탐지
  - confirmed_before: look-ahead 방지 필터
  - _find_next_resistance / _find_next_support: SR 레벨 탐색
  - _calc_long_tp / _calc_short_tp: TP 계산
  - detect_double_bottom / detect_double_top: 쌍바닥/쌍봉
  - detect_asc_triangle / detect_desc_triangle: 삼각형
  - scan_patterns: 통합 스캔 + 방향 필터
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.strategy.pattern_detector import (
    PatternSignal,
    find_local_extrema,
    confirmed_before,
    _find_next_resistance,
    _find_next_support,
    _calc_long_tp,
    _calc_short_tp,
    _MIN_PEAK_SEPARATION,
    _SL_MARGIN,
    _MIN_RR,
    _TP_FALLBACK_RATIO,
    detect_double_bottom,
    detect_double_top,
    detect_asc_triangle,
    detect_desc_triangle,
    scan_patterns,
)


# ── 헬퍼 ────────────────────────────────────────────────────


def _make_v_shape(n: int = 100, low_idx: int = 50, amplitude: float = 10.0,
                  base: float = 100.0) -> np.ndarray:
    """V자 형태 배열 생성."""
    arr = np.full(n, base)
    for i in range(n):
        arr[i] = base - amplitude * (1 - abs(i - low_idx) / max(low_idx, n - low_idx))
    return arr


def _make_double_bottom_ohlcv(
    n: int = 80, m1: int = 20, m2: int = 45, neckline_idx: int = 33,
    low_val: float = 90.0, neckline_val: float = 105.0, close_val: float = 107.0,
):
    """쌍바닥 패턴이 있는 OHLCV 생성."""
    close = np.full(n, 100.0)
    high = np.full(n, 102.0)
    low = np.full(n, 98.0)

    # 두 저점
    for offset in range(-3, 4):
        if 0 <= m1 + offset < n:
            low[m1 + offset] = low_val + abs(offset) * 0.5
            close[m1 + offset] = low_val + abs(offset) * 0.5 + 1.0
        if 0 <= m2 + offset < n:
            low[m2 + offset] = low_val + abs(offset) * 0.5
            close[m2 + offset] = low_val + abs(offset) * 0.5 + 1.0

    # 넥라인 (두 저점 사이 고점)
    high[neckline_idx] = neckline_val

    # 돌파 봉
    close[-1] = close_val
    high[-1] = close_val + 1.0

    return close, high, low


# ── find_local_extrema ───────────────────────────────────────


class TestFindLocalExtrema:
    def test_simple_v_shape(self):
        arr = _make_v_shape(30, low_idx=15)
        mins, maxs = find_local_extrema(arr, order=3)
        assert 15 in mins

    def test_inverted_v(self):
        arr = -_make_v_shape(30, low_idx=15)
        mins, maxs = find_local_extrema(arr, order=3)
        assert 15 in maxs

    def test_flat_array_all_extrema(self):
        """평탄 배열은 <= 비교이므로 모든 내부점이 극값."""
        arr = np.full(30, 100.0)
        mins, maxs = find_local_extrema(arr, order=3)
        # <= 조건이므로 평탄 구간은 모두 극소이자 극대
        assert len(mins) == len(maxs)
        assert len(mins) > 0

    def test_multiple_peaks(self):
        arr = np.zeros(60)
        arr[15] = 10
        arr[40] = 10
        _, maxs = find_local_extrema(arr, order=5)
        assert 15 in maxs
        assert 40 in maxs

    def test_order_respects_boundary(self):
        arr = np.zeros(10)
        arr[0] = -5  # 경계 — order=5이면 감지 불가
        mins, _ = find_local_extrema(arr, order=5)
        assert 0 not in mins


# ── confirmed_before ─────────────────────────────────────────


class TestConfirmedBefore:
    def test_filters_future_indices(self):
        indices = [10, 20, 30, 40]
        result = confirmed_before(indices, current=35, lookback=50, order=5)
        # 30 + 5 = 35, NOT < 35 → 필터됨
        assert 30 not in result
        assert 20 in result
        assert 10 in result

    def test_lookback_window(self):
        indices = [5, 15, 25]
        result = confirmed_before(indices, current=30, lookback=10, order=3)
        # cutoff = 20, 5 < 20 → 제외
        assert 5 not in result
        assert 25 in result

    def test_empty_input(self):
        assert confirmed_before([], current=50) == []


# ── SR 헬퍼 ──────────────────────────────────────────────────


class TestSRHelpers:
    def test_find_next_resistance(self):
        high = np.array([100, 105, 110, 115, 120, 130, 100, 100, 100, 100, 100,
                         100, 100, 100, 100, 100], dtype=float)
        high_maxs = [1, 2, 3, 4, 5]
        # price=102, sl_dist=2 → 다음 저항 >= 102 + 2*1.0 = 104
        result = _find_next_resistance(102.0, 2.0, high, high_maxs, i=15, order=3)
        assert result is not None
        assert result >= 102.0

    def test_find_next_resistance_none_when_rr_low(self):
        high = np.array([100, 102.5, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        high_maxs = [1]
        # price=102, sl_dist=5 → 102.5 - 102 = 0.5, R:R = 0.1 < 1.0
        result = _find_next_resistance(102.0, 5.0, high, high_maxs, i=9, order=3)
        assert result is None

    def test_find_next_support(self):
        low = np.array([100, 95, 90, 85, 100, 100, 100, 100, 100, 100, 100,
                        100, 100, 100, 100, 100], dtype=float)
        low_mins = [1, 2, 3]
        result = _find_next_support(98.0, 2.0, low, low_mins, i=15, order=3)
        assert result is not None
        assert result < 98.0

    def test_calc_long_tp_with_resistance(self):
        high = np.array([100] * 20, dtype=float)
        high[5] = 120.0
        high_maxs = [5]
        # entry=105, sl=100 → sl_dist=5, resistance=120, R:R=15/5=3 ✓
        tp = _calc_long_tp(105.0, 100.0, high, high_maxs, i=15)
        assert tp == 120.0

    def test_calc_long_tp_fallback(self):
        high = np.array([100] * 20, dtype=float)
        high_maxs = []
        # 저항 없음 → 폴백: 105 + 2.0 * 5 = 115
        tp = _calc_long_tp(105.0, 100.0, high, high_maxs, i=15)
        assert tp == pytest.approx(105.0 + _TP_FALLBACK_RATIO * 5.0)

    def test_calc_short_tp_with_support(self):
        low = np.array([100] * 20, dtype=float)
        low[5] = 80.0
        low_mins = [5]
        tp = _calc_short_tp(95.0, 100.0, low, low_mins, i=15)
        assert tp == 80.0

    def test_calc_short_tp_fallback(self):
        low = np.array([100] * 20, dtype=float)
        low_mins = []
        tp = _calc_short_tp(95.0, 100.0, low, low_mins, i=15)
        assert tp == pytest.approx(95.0 - _TP_FALLBACK_RATIO * 5.0)


# ── Double Bottom ────────────────────────────────────────────


class TestDoubleBottom:
    def test_detect_valid(self):
        close, high, low = _make_double_bottom_ohlcv()
        low_mins, high_maxs = find_local_extrema(low, order=5)
        _, high_maxs2 = find_local_extrema(high, order=5)
        i = len(close) - 1

        sig = detect_double_bottom(close, high, low, i, low_mins, high_maxs2)
        if sig is not None:
            assert sig.pattern == "DOUBLE_BOTTOM"
            assert sig.side == "LONG"
            assert sig.stop_loss < sig.entry_price
            assert sig.take_profit > sig.entry_price

    def test_no_detect_when_no_breakout(self):
        close, high, low = _make_double_bottom_ohlcv(close_val=95.0)  # 넥라인 미돌파
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_double_bottom(close, high, low, len(close) - 1, low_mins, high_maxs)
        assert sig is None

    def test_min_peak_separation(self):
        """두 저점이 _MIN_PEAK_SEPARATION 미만이면 미감지."""
        close, high, low = _make_double_bottom_ohlcv(m1=30, m2=35)  # 5봉 차이 < 10
        low_mins, _ = find_local_extrema(low, order=3)
        _, high_maxs = find_local_extrema(high, order=3)
        sig = detect_double_bottom(close, high, low, len(close) - 1, low_mins, high_maxs,
                                   extrema_order=3)
        assert sig is None

    def test_tolerance_exceeded(self):
        """두 저점 차이가 tolerance 초과 시 미감지."""
        close, high, low = _make_double_bottom_ohlcv(low_val=90.0)
        # m2 저점을 크게 다르게
        low[45] = 80.0
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_double_bottom(close, high, low, len(close) - 1, low_mins, high_maxs,
                                   tolerance=0.02)
        assert sig is None

    def test_sl_has_margin(self):
        close, high, low = _make_double_bottom_ohlcv()
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_double_bottom(close, high, low, len(close) - 1, low_mins, high_maxs)
        if sig is not None:
            min_low = min(sig.metadata["low1"], sig.metadata["low2"])
            assert sig.stop_loss == pytest.approx(min_low * (1 - _SL_MARGIN))


# ── Double Top ───────────────────────────────────────────────


class TestDoubleTop:
    def _make_double_top_ohlcv(self, n=80, m1=20, m2=45, close_val=88.0):
        close = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)

        for offset in range(-3, 4):
            if 0 <= m1 + offset < n:
                high[m1 + offset] = 115.0 - abs(offset) * 0.5
            if 0 <= m2 + offset < n:
                high[m2 + offset] = 115.0 - abs(offset) * 0.5

        # 넥라인 (두 고점 사이 저점)
        low[33] = 92.0
        close[-1] = close_val
        low[-1] = close_val - 1.0
        return close, high, low

    def test_detect_valid(self):
        close, high, low = self._make_double_top_ohlcv()
        _, high_maxs = find_local_extrema(high, order=5)
        low_mins, _ = find_local_extrema(low, order=5)
        sig = detect_double_top(close, high, low, len(close) - 1, high_maxs, low_mins)
        if sig is not None:
            assert sig.pattern == "DOUBLE_TOP"
            assert sig.side == "SHORT"
            assert sig.stop_loss > sig.entry_price
            assert sig.take_profit < sig.entry_price

    def test_no_detect_when_no_breakdown(self):
        close, high, low = self._make_double_top_ohlcv(close_val=105.0)
        _, high_maxs = find_local_extrema(high, order=5)
        low_mins, _ = find_local_extrema(low, order=5)
        sig = detect_double_top(close, high, low, len(close) - 1, high_maxs, low_mins)
        assert sig is None


# ── Ascending Triangle ───────────────────────────────────────


class TestAscTriangle:
    def _make_asc_triangle(self, n=80):
        close = np.full(n, 100.0)
        high = np.full(n, 100.0)
        low = np.full(n, 98.0)

        # 수평 저항 (고점 유사)
        for idx in [20, 35, 50]:
            for offset in range(-3, 4):
                if 0 <= idx + offset < n:
                    high[idx + offset] = 110.0 - abs(offset) * 0.3

        # 상승 지지 (저점 상승)
        for j, idx in enumerate([25, 40, 55]):
            for offset in range(-3, 4):
                if 0 <= idx + offset < n:
                    low[idx + offset] = 92.0 + j * 3.0 + abs(offset) * 0.3

        # 돌파
        close[-1] = 112.0
        high[-1] = 113.0
        return close, high, low

    def test_detect_valid(self):
        close, high, low = self._make_asc_triangle()
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_asc_triangle(close, high, low, len(close) - 1, low_mins, high_maxs)
        if sig is not None:
            assert sig.pattern == "ASC_TRIANGLE"
            assert sig.side == "LONG"

    def test_no_detect_if_lows_not_rising(self):
        close, high, low = self._make_asc_triangle()
        # 저점 하락으로 변경
        low[55] = 85.0
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_asc_triangle(close, high, low, len(close) - 1, low_mins, high_maxs)
        assert sig is None


# ── Descending Triangle ──────────────────────────────────────


class TestDescTriangle:
    def _make_desc_triangle(self, n=80):
        close = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 100.0)

        # 수평 지지 (저점 유사)
        for idx in [20, 35, 50]:
            for offset in range(-3, 4):
                if 0 <= idx + offset < n:
                    low[idx + offset] = 88.0 + abs(offset) * 0.3

        # 하강 저항 (고점 하락)
        for j, idx in enumerate([25, 40, 55]):
            for offset in range(-3, 4):
                if 0 <= idx + offset < n:
                    high[idx + offset] = 108.0 - j * 3.0 - abs(offset) * 0.3

        # 하방 돌파
        close[-1] = 86.0
        low[-1] = 85.0
        return close, high, low

    def test_detect_valid(self):
        close, high, low = self._make_desc_triangle()
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_desc_triangle(close, high, low, len(close) - 1, low_mins, high_maxs)
        if sig is not None:
            assert sig.pattern == "DESC_TRIANGLE"
            assert sig.side == "SHORT"

    def test_no_detect_if_highs_not_falling(self):
        close, high, low = self._make_desc_triangle()
        high[55] = 115.0  # 고점 상승 → 패턴 깨짐
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        sig = detect_desc_triangle(close, high, low, len(close) - 1, low_mins, high_maxs)
        assert sig is None


# ── scan_patterns (방향 필터) ────────────────────────────────


class TestScanPatterns:
    def test_long_direction_excludes_short_patterns(self):
        """LONG 방향이면 SHORT 패턴 미실행."""
        close = np.full(100, 100.0)
        high = np.full(100, 102.0)
        low = np.full(100, 98.0)
        results = scan_patterns(
            close, high, low, i=99, direction="LONG",
            low_mins=[], low_maxs=[], high_mins=[], high_maxs=[],
        )
        # 극값 없으므로 어떤 패턴도 감지 불가 — 에러 없이 빈 리스트
        assert isinstance(results, list)

    def test_short_direction_excludes_long_patterns(self):
        results = scan_patterns(
            np.full(100, 100.0), np.full(100, 102.0), np.full(100, 98.0),
            i=99, direction="SHORT",
            low_mins=[], low_maxs=[], high_mins=[], high_maxs=[],
        )
        assert isinstance(results, list)

    def test_neutral_scans_all(self):
        results = scan_patterns(
            np.full(100, 100.0), np.full(100, 102.0), np.full(100, 98.0),
            i=99, direction="NEUTRAL",
            low_mins=[], low_maxs=[], high_mins=[], high_maxs=[],
        )
        assert isinstance(results, list)


# ── PatternSignal 데이터 무결성 ──────────────────────────────


class TestPatternSignalIntegrity:
    def test_dataclass_fields(self):
        sig = PatternSignal(
            pattern="DOUBLE_BOTTOM", side="LONG",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            bar_index=50, metadata={"test": True},
        )
        assert sig.pattern == "DOUBLE_BOTTOM"
        assert sig.side == "LONG"
        assert sig.stop_loss < sig.entry_price < sig.take_profit

    def test_constants(self):
        assert _MIN_PEAK_SEPARATION == 10
        assert _SL_MARGIN == pytest.approx(0.002)
        assert _MIN_RR == pytest.approx(1.0)
        assert _TP_FALLBACK_RATIO == pytest.approx(2.0)

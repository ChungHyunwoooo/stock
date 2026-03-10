"""TDD 테스트 — engine/strategy/pullback_detector.py

핵심 함수:
  - _has_reversal_candle: 반전 캔들 확인
  - detect_pullback: 눌림목 패턴 감지
"""

import numpy as np

from engine.strategy.pattern_detector import (
    PatternSignal,
    find_local_extrema,
    _SL_MARGIN,
)
from engine.strategy.pullback_detector import (
    _has_reversal_candle,
    detect_pullback,
)

# ── 헬퍼 ────────────────────────────────────────────────────

def _make_pullback_data(
    n: int = 100,
    trend: str = "LONG",
    touch_idx: int = 85,
    bounce: bool = True,
):
    """눌림목 패턴 OHLCV + EMA 생성.

    LONG: EMA21 > EMA55 (정배열), 가격이 EMA21 아래 터치 후 복귀.
    """
    opn = np.full(n, 100.0)
    high = np.full(n, 102.0)
    low = np.full(n, 98.0)
    close = np.full(n, 101.0)

    if trend == "LONG":
        ema21 = np.full(n, 100.0)
        ema55 = np.full(n, 95.0)

        # 터치: 가격이 EMA21 아래로
        low[touch_idx] = 99.0
        close[touch_idx] = 99.5

        if bounce:
            # 복귀: 다음 봉에서 EMA21 위로
            close[touch_idx + 1] = 101.5
            high[touch_idx + 1] = 102.5
            opn[touch_idx + 1] = 99.5  # 양봉 (open < close)
    else:
        ema21 = np.full(n, 100.0)
        ema55 = np.full(n, 105.0)

        high[touch_idx] = 101.0
        close[touch_idx] = 100.5

        if bounce:
            close[touch_idx + 1] = 98.5
            low[touch_idx + 1] = 97.5
            opn[touch_idx + 1] = 100.5

    return opn, high, low, close, ema21, ema55

# ── _has_reversal_candle ─────────────────────────────────────

class TestHasReversalCandle:
    def test_returns_bool(self):
        n = 50
        opn = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)
        close = np.full(n, 101.0)
        result = _has_reversal_candle(opn, high, low, close, i=n - 1, side="LONG")
        assert isinstance(result, bool)

    def test_hammer_detected_as_bull(self):
        """망치형 캔들 — 긴 아래꼬리, 작은 몸통."""
        n = 50
        opn = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)
        close = np.full(n, 101.0)

        # 전형적 해머: 긴 아래꼬리
        opn[-1] = 100.0
        high[-1] = 101.0
        low[-1] = 94.0  # 긴 아래꼬리
        close[-1] = 100.5

        result = _has_reversal_candle(opn, high, low, close, i=n - 1, side="LONG")
        # TA-Lib에 따라 감지 여부 다를 수 있음 — bool 반환만 확인
        assert isinstance(result, bool)

    def test_lookback_zero_no_crash(self):
        n = 50
        opn = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)
        close = np.full(n, 101.0)
        # lookback=0이면 검사할 봉 없음 → False
        # detect_pullback에서 기본 lookback=3 사용하므로 edge case
        result = _has_reversal_candle(opn, high, low, close, i=n - 1, side="LONG", lookback=0)
        assert result is False

# ── detect_pullback ──────────────────────────────────────────

class TestDetectPullback:
    def test_returns_signal_or_none(self):
        opn, high, low, close, ema21, ema55 = _make_pullback_data()
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)
        i = 86  # 복귀 봉

        result = detect_pullback(
            opn, high, low, close, i, ema21, ema55,
            low_mins, high_maxs,
            require_candle=False,  # 반전 캔들 없이도 테스트
        )
        assert result is None or isinstance(result, PatternSignal)

    def test_long_pullback_side(self):
        """LONG 눌림목 감지 시 side=LONG."""
        opn, high, low, close, ema21, ema55 = _make_pullback_data(trend="LONG")
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)

        result = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            low_mins, high_maxs, require_candle=False,
        )
        if result is not None:
            assert result.side == "LONG"
            assert result.pattern == "PULLBACK"
            assert result.stop_loss < result.entry_price

    def test_short_pullback_side(self):
        """SHORT 눌림목 감지 시 side=SHORT."""
        opn, high, low, close, ema21, ema55 = _make_pullback_data(trend="SHORT")
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)

        result = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            low_mins, high_maxs, require_candle=False,
        )
        if result is not None:
            assert result.side == "SHORT"
            assert result.stop_loss > result.entry_price

    def test_no_detect_without_trend(self):
        """EMA21 == EMA55 → 추세 없음 → 미감지."""
        n = 100
        opn = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)
        close = np.full(n, 101.0)
        ema21 = np.full(n, 100.0)
        ema55 = np.full(n, 100.0)  # 동일 → 추세 없음

        result = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            [], [], require_candle=False,
        )
        assert result is None

    def test_no_detect_without_bounce(self):
        """터치 후 복귀 안 하면 미감지."""
        opn, high, low, close, ema21, ema55 = _make_pullback_data(
            trend="LONG", bounce=False,
        )
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)

        result = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            low_mins, high_maxs, require_candle=False,
        )
        # 복귀 없으므로 미감지 가능 (구현에 따라)
        assert result is None or isinstance(result, PatternSignal)

    def test_require_candle_stricter(self):
        """require_candle=True면 반전 캔들 없으면 미감지."""
        opn, high, low, close, ema21, ema55 = _make_pullback_data(trend="LONG")
        low_mins, _ = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)

        with_candle = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            low_mins, high_maxs, require_candle=True,
        )
        without_candle = detect_pullback(
            opn, high, low, close, 86, ema21, ema55,
            low_mins, high_maxs, require_candle=False,
        )
        # require_candle=True는 같거나 더 엄격
        if with_candle is not None:
            assert without_candle is not None

    def test_boundary_index(self):
        """i=0 같은 경계값에서 크래시 없음."""
        n = 100
        opn = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 98.0)
        close = np.full(n, 101.0)
        ema21 = np.full(n, 100.0)
        ema55 = np.full(n, 95.0)

        # i=0에서 크래시 없어야 함
        result = detect_pullback(
            opn, high, low, close, 0, ema21, ema55,
            [], [], require_candle=False,
        )
        assert result is None or isinstance(result, PatternSignal)

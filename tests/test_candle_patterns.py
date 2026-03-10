"""TDD 테스트 — engine/strategy/candle_patterns.py

핵심 함수:
  - scan_candle_patterns: TA-Lib 캔들 패턴 스캔
  - format_candle_signals: 디스코드 포맷
  - get_candle_bias: 종합 방향 편향
  - CandleSignal 데이터 모델
  - CANDLE_PATTERNS 레지스트리
"""

import numpy as np

from engine.strategy.candle_patterns import (
    CANDLE_PATTERNS,
    CandleSignal,
    scan_candle_patterns,
    format_candle_signals,
    get_candle_bias,
)

# ── CANDLE_PATTERNS 레지스트리 ────────────────────────────────

class TestCandlePatternRegistry:
    def test_has_21_patterns(self):
        assert len(CANDLE_PATTERNS) == 21

    def test_all_have_korean_name_and_importance(self):
        for func_name, (kr_name, importance) in CANDLE_PATTERNS.items():
            assert isinstance(kr_name, str) and len(kr_name) > 0, f"{func_name} 한글명 누락"
            assert importance in (1, 2, 3), f"{func_name} 중요도 범위 오류: {importance}"

    def test_key_patterns_exist(self):
        assert "CDLENGULFING" in CANDLE_PATTERNS
        assert "CDL3WHITESOLDIERS" in CANDLE_PATTERNS
        assert "CDLHAMMER" in CANDLE_PATTERNS
        assert "CDLSHOOTINGSTAR" in CANDLE_PATTERNS

# ── CandleSignal 모델 ───────────────────────────────────────

class TestCandleSignal:
    def test_creation(self):
        sig = CandleSignal(
            name="CDLENGULFING", kr_name="장악형",
            direction="BULL", strength=100, importance=2,
        )
        assert sig.direction == "BULL"
        assert sig.importance == 2

# ── scan_candle_patterns ─────────────────────────────────────

def _make_bullish_engulfing(n: int = 50) -> tuple:
    """강한 양봉 장악형 데이터."""
    open_ = np.full(n, 100.0)
    high = np.full(n, 102.0)
    low = np.full(n, 98.0)
    close = np.full(n, 101.0)

    # 음봉 → 양봉 (장악형)
    open_[-2] = 101.0
    close[-2] = 99.0
    low[-2] = 98.5
    high[-2] = 101.5

    open_[-1] = 98.0
    close[-1] = 103.0
    low[-1] = 97.5
    high[-1] = 103.5

    return open_, high, low, close

class TestScanCandlePatterns:
    def test_returns_list(self):
        n = 50
        result = scan_candle_patterns(
            np.full(n, 100.0), np.full(n, 102.0),
            np.full(n, 98.0), np.full(n, 101.0),
        )
        assert isinstance(result, list)

    def test_all_items_are_candle_signal(self):
        open_, high, low, close = _make_bullish_engulfing()
        result = scan_candle_patterns(open_, high, low, close)
        for sig in result:
            assert isinstance(sig, CandleSignal)

    def test_sorted_by_importance_desc(self):
        open_, high, low, close = _make_bullish_engulfing()
        result = scan_candle_patterns(open_, high, low, close)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i].importance >= result[i + 1].importance

    def test_no_duplicates(self):
        open_, high, low, close = _make_bullish_engulfing()
        result = scan_candle_patterns(open_, high, low, close)
        names = [s.name for s in result]
        assert len(names) == len(set(names))

    def test_lookback_parameter(self):
        open_, high, low, close = _make_bullish_engulfing()
        result_3 = scan_candle_patterns(open_, high, low, close, lookback=3)
        result_1 = scan_candle_patterns(open_, high, low, close, lookback=1)
        # lookback=1이면 더 적거나 같은 패턴 감지
        assert len(result_1) <= len(result_3)

    def test_empty_array_no_crash(self):
        n = 5  # 아주 짧은 배열
        result = scan_candle_patterns(
            np.full(n, 100.0), np.full(n, 102.0),
            np.full(n, 98.0), np.full(n, 101.0),
        )
        assert isinstance(result, list)

# ── format_candle_signals ────────────────────────────────────

class TestFormatCandleSignals:
    def test_empty_returns_default(self):
        assert format_candle_signals([]) == "캔들: 없음"

    def test_single_bull(self):
        sig = CandleSignal("CDLENGULFING", "장악형", "BULL", 100, 2)
        result = format_candle_signals([sig])
        assert "▲" in result
        assert "장악형" in result

    def test_single_bear(self):
        sig = CandleSignal("CDLSHOOTINGSTAR", "유성형", "BEAR", 100, 2)
        result = format_candle_signals([sig])
        assert "▼" in result
        assert "유성형" in result

    def test_max_5_items(self):
        sigs = [
            CandleSignal(f"CDL{i}", f"패턴{i}", "BULL", 100, 2)
            for i in range(10)
        ]
        result = format_candle_signals(sigs)
        # 최대 5개만 표시
        assert result.count("▲") <= 5

    def test_importance_stars(self):
        sig = CandleSignal("CDL3WHITESOLDIERS", "삼백병", "BULL", 100, 3)
        result = format_candle_signals([sig])
        assert "***" in result

# ── get_candle_bias ──────────────────────────────────────────

class TestGetCandleBias:
    def test_empty_neutral(self):
        direction, confidence = get_candle_bias([])
        assert direction == "NEUTRAL"
        assert confidence == 0.0

    def test_pure_bull(self):
        sigs = [CandleSignal("A", "a", "BULL", 100, 3)]
        direction, confidence = get_candle_bias(sigs)
        assert direction == "BULL"
        assert 0.0 < confidence <= 1.0

    def test_pure_bear(self):
        sigs = [CandleSignal("A", "a", "BEAR", 100, 3)]
        direction, confidence = get_candle_bias(sigs)
        assert direction == "BEAR"
        assert 0.0 < confidence <= 1.0

    def test_mixed_signals_stronger_wins(self):
        sigs = [
            CandleSignal("A", "a", "BULL", 100, 3),
            CandleSignal("B", "b", "BULL", 100, 2),
            CandleSignal("C", "c", "BEAR", 100, 1),
        ]
        direction, confidence = get_candle_bias(sigs)
        assert direction == "BULL"

    def test_equal_signals_neutral(self):
        sigs = [
            CandleSignal("A", "a", "BULL", 100, 2),
            CandleSignal("B", "b", "BEAR", 100, 2),
        ]
        direction, _ = get_candle_bias(sigs)
        assert direction == "NEUTRAL"

    def test_confidence_bounded(self):
        sigs = [CandleSignal(f"CDL{i}", f"p{i}", "BULL", 200, 3) for i in range(10)]
        _, confidence = get_candle_bias(sigs)
        assert confidence <= 1.0

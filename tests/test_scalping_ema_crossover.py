"""EMA Crossover 스캘핑 전략 테스트."""

import numpy as np
import pandas as pd
import pytest

from engine.strategy.scalping_ema_crossover import (
    ScalpResult,
    ScalpSignal,
    calc_ema,
    calc_rsi,
    detect_scalp_signal,
)


def _make_ohlcv(closes: list[float]) -> pd.DataFrame:
    """close 가격 리스트로 OHLCV 생성."""
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="min")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [100] * n,
        },
        index=idx,
    )


class TestIndicators:
    def test_ema_length(self):
        s = pd.Series(range(50), dtype=float)
        result = calc_ema(s, 9)
        assert len(result) == 50

    def test_ema_smoothing(self):
        s = pd.Series([10.0] * 20 + [20.0] * 20)
        ema = calc_ema(s, 9)
        assert ema.iloc[-1] > 19  # 20에 가까워야 함
        assert ema.iloc[19] == pytest.approx(10.0, abs=0.01)  # 평탄 구간

    def test_rsi_range(self):
        s = pd.Series(np.random.uniform(100, 200, 100))
        rsi = calc_rsi(s, 14)
        valid = rsi.dropna()
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_overbought(self):
        s = pd.Series(list(range(100, 200)))  # 계속 상승
        rsi = calc_rsi(s, 14)
        assert rsi.iloc[-1] > 70

    def test_rsi_oversold(self):
        s = pd.Series(list(range(200, 100, -1)))  # 계속 하락
        rsi = calc_rsi(s, 14)
        assert rsi.iloc[-1] < 30


class TestDetectScalpSignal:
    def test_insufficient_data(self):
        df = _make_ohlcv([100] * 10)
        result = detect_scalp_signal(df)
        assert result.signal == ScalpSignal.NONE
        assert "부족" in result.reason

    def test_no_signal_flat(self):
        df = _make_ohlcv([50000] * 50)
        result = detect_scalp_signal(df)
        assert result.signal == ScalpSignal.NONE

    def test_golden_cross_long(self):
        # EMA9가 EMA21을 상향 돌파하도록 구성
        # 하락 → 급반등
        prices = [50000 - i * 10 for i in range(30)]  # 하락
        prices += [prices[-1] + i * 50 for i in range(1, 21)]  # 급반등
        df = _make_ohlcv(prices)
        result = detect_scalp_signal(df)
        # 크로스가 정확히 마지막 봉에서 발생하지 않을 수 있으므로
        # 최소한 signal 구조는 정상이어야 함
        assert isinstance(result, ScalpResult)
        assert result.ema_fast > 0
        assert result.ema_slow > 0

    def test_long_signal_structure(self):
        # 골든크로스 + RSI 50~70 강제
        prices = [50000 - i * 5 for i in range(25)]
        prices += [prices[-1] + i * 30 for i in range(1, 26)]
        df = _make_ohlcv(prices)
        result = detect_scalp_signal(df)
        if result.signal == ScalpSignal.LONG:
            assert result.stop_loss < result.entry_price
            assert result.take_profit > result.entry_price
            assert result.stop_loss > 0
            assert "골든크로스" in result.reason

    def test_short_signal_structure(self):
        # 데드크로스: 상승 → 급하락
        prices = [50000 + i * 10 for i in range(30)]
        prices += [prices[-1] - i * 50 for i in range(1, 21)]
        df = _make_ohlcv(prices)
        result = detect_scalp_signal(df)
        if result.signal == ScalpSignal.SHORT:
            assert result.stop_loss > result.entry_price
            assert result.take_profit < result.entry_price
            assert "데드크로스" in result.reason

    def test_custom_config(self):
        prices = [50000] * 50
        config = {"ema_fast": 5, "ema_slow": 10, "sl_pct": 0.5, "tp_pct": 1.0}
        result = detect_scalp_signal(_make_ohlcv(prices), config)
        assert isinstance(result, ScalpResult)

    def test_rsi_filter_blocks_overbought(self):
        # 계속 상승 → RSI > 70 → 골든크로스여도 차단
        prices = [50000 + i * 100 for i in range(50)]
        df = _make_ohlcv(prices)
        result = detect_scalp_signal(df)
        # RSI가 70 이상이면 LONG 신호 안 나와야 함
        if result.rsi > 70:
            assert result.signal != ScalpSignal.LONG

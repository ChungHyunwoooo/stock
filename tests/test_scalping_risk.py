"""스캘핑 리스크 모듈 테스트 — 데이터 기반 동적 SL/TP."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.strategy.scalping_risk import (
    ScalpRiskConfig,
    calc_atr,
    calc_atr_percentile,
    calculate_dynamic_leverage,
    calculate_dynamic_sl_tp,
    calculate_scalp_risk,
)


def _make_ohlcv(n: int = 50, base_price: float = 50000.0, volatility: float = 0.005) -> pd.DataFrame:
    """테스트용 OHLCV 생성."""
    np.random.seed(42)
    closes = [base_price]
    for _ in range(n - 1):
        change = np.random.normal(0, volatility)
        closes.append(closes[-1] * (1 + change))

    closes = np.array(closes)
    highs = closes * (1 + np.random.uniform(0.001, 0.003, n))
    lows = closes * (1 - np.random.uniform(0.001, 0.003, n))
    opens = closes * (1 + np.random.uniform(-0.002, 0.002, n))
    volumes = np.random.uniform(100, 1000, n)

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


# ── ATR ──────────────────────────────────────────────────────


class TestCalcATR:
    def test_atr_returns_series(self):
        df = _make_ohlcv()
        atr = calc_atr(df, period=14)
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(df)

    def test_atr_positive(self):
        df = _make_ohlcv()
        atr = calc_atr(df, period=14)
        assert atr.iloc[-1] > 0

    def test_atr_higher_volatility(self):
        df_low = _make_ohlcv(volatility=0.002)
        df_high = _make_ohlcv(volatility=0.02)
        atr_low = calc_atr(df_low).iloc[-1]
        atr_high = calc_atr(df_high).iloc[-1]
        assert atr_high > atr_low


# ── ATR Percentile ───────────────────────────────────────────


class TestATRPercentile:
    def test_range_0_to_1(self):
        df = _make_ohlcv(n=100)
        atr_series = calc_atr(df)
        pctile = calc_atr_percentile(atr_series, lookback=50)
        assert 0.0 <= pctile <= 1.0

    def test_high_vol_spike_high_percentile(self):
        """변동성 급등 시 percentile 높아야 함."""
        df = _make_ohlcv(n=100, volatility=0.002)
        # 마지막 10봉에 큰 변동 추가
        df.iloc[-10:, df.columns.get_loc("high")] *= 1.05
        df.iloc[-10:, df.columns.get_loc("low")] *= 0.95
        atr_series = calc_atr(df)
        pctile = calc_atr_percentile(atr_series)
        assert pctile > 0.7

    def test_short_data_returns_midpoint(self):
        """데이터 1봉이면 0.5 반환."""
        df = _make_ohlcv(n=2)
        atr_series = calc_atr(df)
        # 1봉짜리 슬라이스
        pctile = calc_atr_percentile(atr_series.iloc[:1])
        assert pctile == 0.5


# ── 동적 SL/TP ──────────────────────────────────────────────


class TestDynamicSLTP:
    def test_long_sl_below_entry(self):
        sl, tp, sl_pct, tp_pct = calculate_dynamic_sl_tp(50000, 100, 0.5, "long")
        assert sl < 50000
        assert tp > 50000

    def test_short_sl_above_entry(self):
        sl, tp, sl_pct, tp_pct = calculate_dynamic_sl_tp(50000, 100, 0.5, "short")
        assert sl > 50000
        assert tp < 50000

    def test_low_pctile_tighter_sl(self):
        """저변동성 percentile → SL 더 타이트."""
        _, _, sl_low, _ = calculate_dynamic_sl_tp(50000, 100, 0.1, "long")
        _, _, sl_high, _ = calculate_dynamic_sl_tp(50000, 100, 0.9, "long")
        assert sl_low < sl_high  # 저변동성 시 SL% 작음

    def test_low_pctile_higher_rr(self):
        """저변동성 percentile → R:R 더 높음."""
        _, _, sl_low, tp_low = calculate_dynamic_sl_tp(50000, 100, 0.1, "long")
        _, _, sl_high, tp_high = calculate_dynamic_sl_tp(50000, 100, 0.9, "long")
        rr_low = tp_low / sl_low if sl_low > 0 else 0
        rr_high = tp_high / sl_high if sl_high > 0 else 0
        assert rr_low > rr_high  # 저변동성 시 R:R 높음

    def test_sl_pct_clamping(self):
        cfg = ScalpRiskConfig(min_sl_pct=0.5, max_sl_pct=1.0)
        # ATR이 매우 작을 때 → min_sl_pct 적용
        _, _, sl_pct, _ = calculate_dynamic_sl_tp(50000, 1, 0.5, "long", cfg)
        assert sl_pct >= cfg.min_sl_pct

        # ATR이 매우 클 때 → max_sl_pct 적용
        _, _, sl_pct, _ = calculate_dynamic_sl_tp(50000, 5000, 0.5, "long", cfg)
        assert sl_pct <= cfg.max_sl_pct

    def test_extreme_percentiles(self):
        """pctile=0과 pctile=1에서도 정상 동작."""
        sl0, tp0, _, _ = calculate_dynamic_sl_tp(50000, 100, 0.0, "long")
        sl1, tp1, _, _ = calculate_dynamic_sl_tp(50000, 100, 1.0, "long")
        assert sl0 < 50000 and tp0 > 50000
        assert sl1 < 50000 and tp1 > 50000


# ── 동적 레버리지 ───────────────────────────────────────────


class TestDynamicLeverage:
    def test_low_pctile_high_leverage(self):
        """저변동성 → 레버리지 높게."""
        lev = calculate_dynamic_leverage(0.1, 0.1)
        cfg = ScalpRiskConfig()
        assert lev > cfg.leverage_min

    def test_high_pctile_low_leverage(self):
        """고변동성 → 레버리지 낮게."""
        lev = calculate_dynamic_leverage(2.0, 0.9)
        cfg = ScalpRiskConfig()
        assert lev <= cfg.leverage_min + 2  # 낮은 쪽에 가까워야 함

    def test_leverage_bounds(self):
        cfg = ScalpRiskConfig(leverage_min=3, leverage_max=10)
        lev_low = calculate_dynamic_leverage(5.0, 1.0, cfg)  # 최고 변동성
        lev_high = calculate_dynamic_leverage(0.01, 0.0, cfg)  # 최저 변동성
        assert lev_low == cfg.leverage_min
        assert lev_high == cfg.leverage_max

    def test_zero_atr_returns_min(self):
        lev = calculate_dynamic_leverage(0.0, 0.5)
        assert lev == ScalpRiskConfig().leverage_min

    def test_monotonic_decrease(self):
        """percentile 증가 → 레버리지 감소 (단조)."""
        leverages = [calculate_dynamic_leverage(0.5, p / 10) for p in range(11)]
        for i in range(len(leverages) - 1):
            assert leverages[i] >= leverages[i + 1]


# ── 종합 리스크 계산 ────────────────────────────────────────


class TestCalculateScalpRisk:
    def test_returns_valid_result(self):
        df = _make_ohlcv()
        price = float(df["close"].iloc[-1])
        result = calculate_scalp_risk(df, price, "long", capital=10000)

        assert result.stop_loss < price
        assert result.take_profit > price
        assert result.leverage >= 2
        assert result.quantity > 0
        assert result.rr_ratio >= 1.5  # rr_min
        assert result.atr > 0
        assert result.risk_amount > 0
        assert 0.0 <= result.atr_pctile <= 1.0

    def test_short_direction(self):
        df = _make_ohlcv()
        price = float(df["close"].iloc[-1])
        result = calculate_scalp_risk(df, price, "short", capital=10000)

        assert result.stop_loss > price
        assert result.take_profit < price

    def test_max_position_cap(self):
        df = _make_ohlcv()
        price = float(df["close"].iloc[-1])
        cfg = ScalpRiskConfig(max_position_pct=0.1, risk_per_trade_pct=0.5)
        result = calculate_scalp_risk(df, price, "long", capital=10000, config=cfg)

        max_val = 10000 * cfg.max_position_pct * result.leverage
        assert result.position_value <= max_val + 1  # 반올림 허용

    def test_reason_contains_percentile(self):
        df = _make_ohlcv()
        price = float(df["close"].iloc[-1])
        result = calculate_scalp_risk(df, price, "long", capital=10000)

        assert "ATR=" in result.reason
        assert "p" in result.reason  # percentile 표시
        assert "SL=" in result.reason
        assert "R:R=" in result.reason

    def test_small_capital(self):
        df = _make_ohlcv()
        price = float(df["close"].iloc[-1])
        result = calculate_scalp_risk(df, price, "long", capital=100)
        assert result.quantity >= 0
        assert result.risk_amount <= 100

    def test_high_vol_vs_low_vol(self):
        """고변동성 데이터 → SL 넓음 (ATR 절대값 차이)."""
        df_low = _make_ohlcv(n=100, volatility=0.002)
        df_high = _make_ohlcv(n=100, volatility=0.02)

        price_low = float(df_low["close"].iloc[-1])
        price_high = float(df_high["close"].iloc[-1])

        r_low = calculate_scalp_risk(df_low, price_low, "long", capital=10000)
        r_high = calculate_scalp_risk(df_high, price_high, "long", capital=10000)

        # ATR 절대값이 높으면 SL%도 넓어야 함
        assert r_high.sl_pct > r_low.sl_pct
        assert r_high.atr_pct > r_low.atr_pct

    def test_percentile_affects_leverage(self):
        """같은 데이터에서 percentile 높을수록 레버리지 낮음."""
        cfg = ScalpRiskConfig(leverage_min=2, leverage_max=20)
        lev_low_pctile = calculate_dynamic_leverage(0.5, 0.1, cfg)
        lev_high_pctile = calculate_dynamic_leverage(0.5, 0.9, cfg)
        assert lev_low_pctile > lev_high_pctile

    def test_leverage_sl_safety_cap(self):
        """leverage × SL% < max_loss_pct (50%) 보장."""
        df = _make_ohlcv(n=100)
        price = float(df["close"].iloc[-1])
        cfg = ScalpRiskConfig(max_loss_pct=0.5)
        result = calculate_scalp_risk(df, price, "long", capital=10000, config=cfg)

        # leverage × SL% < 50%
        actual_loss_pct = result.leverage * result.sl_pct / 100
        assert actual_loss_pct < cfg.max_loss_pct + 0.01  # 부동소수점 허용

    def test_max_account_loss_5pct(self):
        """거래당 최대 계좌 손실 = 투입비율(10%) × 투입금손실(50%) = 5%.

        position_value는 이미 레버리지 반영된 명목가치.
        실제 손실 = position_value × SL% (레버리지 이중 계산 아님).
        """
        df = _make_ohlcv(n=100)
        price = float(df["close"].iloc[-1])
        capital = 10000
        cfg = ScalpRiskConfig(max_position_pct=0.1, max_loss_pct=0.5)
        result = calculate_scalp_risk(df, price, "long", capital=capital, config=cfg)

        # 실제 손실 = position_value × SL%
        max_trade_loss = result.position_value * result.sl_pct / 100
        max_account_loss_pct = max_trade_loss / capital
        # 10% 투입 × leverage × SL% < 50% → 계좌 대비 < 5%
        assert max_account_loss_pct <= 0.05 + 0.01

    def test_high_sl_caps_leverage(self):
        """SL이 2%면 leverage 최대 25x (50/2)."""
        df = _make_ohlcv(n=100, volatility=0.02)
        price = float(df["close"].iloc[-1])
        cfg = ScalpRiskConfig(
            max_loss_pct=0.5,
            leverage_max=50,  # 높게 설정해도
        )
        result = calculate_scalp_risk(df, price, "long", capital=10000, config=cfg)

        if result.sl_pct >= 2.0:
            assert result.leverage <= 25  # 50% / 2% = 25x

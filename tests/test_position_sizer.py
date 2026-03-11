"""PositionSizer + ScalpRiskConfig.for_timeframe() 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine.strategy.scalping_risk import ScalpRiskConfig
from engine.strategy.position_sizer import PositionSizer, PositionSizeResult


def _make_df(n: int = 120, price: float = 50000.0) -> pd.DataFrame:
    """테스트용 OHLCV DataFrame 생성."""
    rng = np.random.default_rng(42)
    closes = price + np.cumsum(rng.normal(0, price * 0.001, n))
    return pd.DataFrame({
        "open": closes - rng.uniform(0, price * 0.002, n),
        "high": closes + rng.uniform(0, price * 0.003, n),
        "low": closes - rng.uniform(0, price * 0.003, n),
        "close": closes,
        "volume": rng.uniform(100, 1000, n),
    })


# --- ScalpRiskConfig.for_timeframe() ---

class TestScalpRiskConfigTimeframe:
    def test_scalping_preset_5m(self):
        """Test 1: 5m -> scalping preset (다른 sl_mult_min/max, rr_min/max)."""
        cfg = ScalpRiskConfig.for_timeframe("5m")
        default = ScalpRiskConfig()
        assert cfg.sl_mult_min != default.sl_mult_min
        assert cfg.sl_mult_max != default.sl_mult_max
        assert cfg.sl_mult_min == 0.5
        assert cfg.sl_mult_max == 1.5

    def test_swing_preset_1d(self):
        """Test 2: 1d -> swing preset."""
        cfg = ScalpRiskConfig.for_timeframe("1d")
        assert cfg.sl_mult_min == 1.5
        assert cfg.sl_mult_max == 4.0
        assert cfg.rr_min == 2.0
        assert cfg.rr_max == 5.0
        assert cfg.min_sl_pct == 0.5
        assert cfg.max_sl_pct == 5.0

    def test_unknown_timeframe_fallback(self):
        """Test 3: unknown -> daytrading default."""
        cfg = ScalpRiskConfig.for_timeframe("unknown")
        default = ScalpRiskConfig()
        assert cfg.sl_mult_min == default.sl_mult_min
        assert cfg.sl_mult_max == default.sl_mult_max
        assert cfg.rr_min == default.rr_min
        assert cfg.rr_max == default.rr_max


# --- PositionSizer ---

class TestPositionSizer:
    def _make_trade_stats(self, n_trades: int = 30) -> dict:
        return {
            "win_rate": 0.6,
            "avg_win": 2.0,
            "avg_loss": 1.0,
            "n_trades": n_trades,
        }

    def test_kelly_applied_with_enough_trades(self):
        """Test 4: 거래 이력 20건 이상 -> Kelly 적용, ATR+Kelly x position_size_factor."""
        df = _make_df()
        rm = MagicMock()
        rm.position_size_factor.return_value = 1.0

        sizer = PositionSizer(risk_manager=rm, min_trades_for_kelly=20)
        result = sizer.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(30),
        )
        assert isinstance(result, PositionSizeResult)
        assert result.kelly_applied is True
        assert result.quantity > 0

    def test_kelly_not_applied_with_few_trades(self):
        """Test 5: 거래 이력 20건 미만 -> 고정 risk_per_trade_pct."""
        df = _make_df()
        rm = MagicMock()
        rm.position_size_factor.return_value = 1.0

        sizer = PositionSizer(risk_manager=rm, min_trades_for_kelly=20)
        result = sizer.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(10),
        )
        assert result.kelly_applied is False
        assert result.quantity > 0

    def test_position_size_factor_halves_quantity(self):
        """Test 6: position_size_factor=0.5 -> quantity 절반."""
        df = _make_df()

        rm_full = MagicMock()
        rm_full.position_size_factor.return_value = 1.0
        sizer_full = PositionSizer(risk_manager=rm_full)
        r_full = sizer_full.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(5),
        )

        rm_half = MagicMock()
        rm_half.position_size_factor.return_value = 0.5
        sizer_half = PositionSizer(risk_manager=rm_half)
        r_half = sizer_half.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(5),
        )

        assert abs(r_half.quantity - r_full.quantity * 0.5) < 1e-6

    def test_allocation_weight_scales_capital(self):
        """Test 7: allocation_weight=0.3 -> capital * 0.3으로 사이징."""
        df = _make_df()

        rm = MagicMock()
        rm.position_size_factor.return_value = 1.0
        sizer = PositionSizer(risk_manager=rm)

        r_full = sizer.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(5),
            allocation_weight=1.0,
        )
        r_partial = sizer.calculate(
            df=df, entry_price=50000.0, side="long", capital=10000.0,
            trade_stats=self._make_trade_stats(5),
            allocation_weight=0.3,
        )

        # allocation_weight=0.3 means capital*0.3 -> quantity proportional
        assert abs(r_partial.quantity - r_full.quantity * 0.3) < 1e-6

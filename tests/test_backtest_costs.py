"""Tests for BacktestRunner slippage + fee integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.backtest.runner import BacktestRunner, TradeRecord
from engine.backtest.slippage import NoSlippage, VolumeAdjustedSlippage


def _make_ohlcv_with_signals(
    prices: list[float],
    signals: list[int],
) -> pd.DataFrame:
    """Create a deterministic OHLCV DataFrame with signal column.

    All OHLC values are set to the same price for simplicity.
    """
    dates = pd.date_range("2025-01-01", periods=len(prices), freq="D")
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000.0] * len(prices),
            "signal": signals,
        },
        index=dates,
    )
    return df


class TestBacktestRunnerBackwardCompat:
    """Default constructor preserves existing behaviour."""

    def test_default_constructor_no_args(self) -> None:
        """BacktestRunner() with no args should work (backward compatible)."""
        runner = BacktestRunner()
        assert runner._slippage_model is not None
        assert runner._fee_rate == 0.0

    def test_default_produces_same_result_as_no_costs(self) -> None:
        """NoSlippage + fee=0 should equal the original behaviour."""
        runner_default = BacktestRunner()
        runner_explicit = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.0)

        # Simple up trade: buy at 100, sell at 110
        prices = [100.0, 100.0, 110.0, 110.0]
        signals = [0, 1, -1, 0]
        df = _make_ohlcv_with_signals(prices, signals)

        eq1, trades1 = runner_default._simulate(df, 10_000.0, symbol="TEST/USDT")
        eq2, trades2 = runner_explicit._simulate(df, 10_000.0, symbol="TEST/USDT")

        assert eq1.iloc[-1] == pytest.approx(eq2.iloc[-1])
        assert len(trades1) == len(trades2)


class TestBacktestRunnerSlippage:
    """Slippage applied to entry/exit prices."""

    def test_slippage_reduces_profit(self) -> None:
        """VolumeAdjustedSlippage should produce lower final capital."""
        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = {
            "avg_spread_pct": 0.001,
            "avg_depth_usd_10": 500_000.0,
        }

        runner_no_slip = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.0)
        runner_with_slip = BacktestRunner(
            slippage_model=VolumeAdjustedSlippage(depth_cache=mock_cache),
            fee_rate=0.0,
        )

        # Clear uptrend: buy at 100, sell at 120
        prices = [100.0, 100.0, 120.0, 120.0]
        signals = [0, 1, -1, 0]
        df = _make_ohlcv_with_signals(prices, signals)

        eq_no, _ = runner_no_slip._simulate(df, 10_000.0, symbol="BTC/USDT")
        eq_with, _ = runner_with_slip._simulate(df, 10_000.0, symbol="BTC/USDT")

        assert eq_with.iloc[-1] < eq_no.iloc[-1]

    def test_entry_price_adjusted_by_slippage(self) -> None:
        """Buy entry price should be higher due to slippage."""
        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = {
            "avg_spread_pct": 0.002,
            "avg_depth_usd_10": 100_000.0,
        }

        runner = BacktestRunner(
            slippage_model=VolumeAdjustedSlippage(depth_cache=mock_cache),
            fee_rate=0.0,
        )

        prices = [100.0, 100.0, 110.0, 110.0]
        signals = [0, 1, -1, 0]
        df = _make_ohlcv_with_signals(prices, signals)

        _, trades = runner._simulate(df, 10_000.0, symbol="BTC/USDT")
        assert len(trades) == 1
        # Entry price should be > close (100) due to slippage
        assert trades[0].entry_price > 100.0


class TestBacktestRunnerFees:
    """Fee deduction on entry and exit."""

    def test_fee_reduces_profit(self) -> None:
        """Fee should reduce final capital vs no fee."""
        runner_no_fee = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.0)
        runner_with_fee = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.001)

        prices = [100.0, 100.0, 120.0, 120.0]
        signals = [0, 1, -1, 0]
        df = _make_ohlcv_with_signals(prices, signals)

        eq_no, _ = runner_no_fee._simulate(df, 10_000.0, symbol="TEST/USDT")
        eq_with, _ = runner_with_fee._simulate(df, 10_000.0, symbol="TEST/USDT")

        assert eq_with.iloc[-1] < eq_no.iloc[-1]


class TestBacktestRunnerCombined:
    """Slippage + fee combined."""

    def test_combined_costs_reduce_profit_more(self) -> None:
        """Both slippage and fee together should reduce profit more than either alone."""
        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = {
            "avg_spread_pct": 0.001,
            "avg_depth_usd_10": 500_000.0,
        }

        runner_none = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.0)
        runner_slip_only = BacktestRunner(
            slippage_model=VolumeAdjustedSlippage(depth_cache=mock_cache),
            fee_rate=0.0,
        )
        runner_fee_only = BacktestRunner(slippage_model=NoSlippage(), fee_rate=0.001)
        runner_both = BacktestRunner(
            slippage_model=VolumeAdjustedSlippage(depth_cache=mock_cache),
            fee_rate=0.001,
        )

        prices = [100.0, 100.0, 120.0, 120.0]
        signals = [0, 1, -1, 0]
        df = _make_ohlcv_with_signals(prices, signals)

        eq_none, _ = runner_none._simulate(df, 10_000.0, symbol="BTC/USDT")
        eq_slip, _ = runner_slip_only._simulate(df, 10_000.0, symbol="BTC/USDT")
        eq_fee, _ = runner_fee_only._simulate(df, 10_000.0, symbol="BTC/USDT")
        eq_both, _ = runner_both._simulate(df, 10_000.0, symbol="BTC/USDT")

        # Both combined should be strictly less than either alone
        assert eq_both.iloc[-1] < eq_slip.iloc[-1]
        assert eq_both.iloc[-1] < eq_fee.iloc[-1]
        assert eq_both.iloc[-1] < eq_none.iloc[-1]

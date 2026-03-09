"""Tests for engine/strategy/engine.py — StrategyEngine.generate_signals."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine.schema import (
    Condition,
    ConditionGroup,
    ConditionOp,
    IndicatorDef,
    RiskParams,
    StrategyDefinition,
    StrategyStatus,
)
from engine.strategy.engine import StrategyEngine


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """30-row OHLCV DataFrame for engine tests."""
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100.0, 130.0, n)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.ones(n) * 1_000_000,
        },
        index=idx,
    )


def _make_rsi_series(index: pd.Index, cross_above_idx: int, cross_below_idx: int) -> pd.Series:
    """Build an RSI series with deliberate crosses at given positions."""
    values = np.full(len(index), 50.0)
    # crosses_above 30 at cross_above_idx: prev<=30, cur>30
    values[cross_above_idx - 1] = 28.0
    values[cross_above_idx] = 32.0
    # crosses_below 70 at cross_below_idx: prev>=70, cur<70
    values[cross_below_idx - 1] = 72.0
    values[cross_below_idx] = 68.0
    return pd.Series(values, index=index)


def test_generate_signals_single_indicator(ohlcv_df):
    """generate_signals produces correct entry/exit signals with mocked RSI."""
    rsi_series = _make_rsi_series(ohlcv_df.index, cross_above_idx=10, cross_below_idx=20)

    def mock_rsi_fn(df, **kwargs):
        return rsi_series

    strategy = StrategyDefinition(
        name="Test RSI",
        markets=["us_stock"],
        indicators=[IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14")],
        entry=ConditionGroup(
            logic="and",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_above, right=30)],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_below, right=70)],
        ),
        risk=RiskParams(stop_loss_pct=0.03, take_profit_pct=0.09),
    )

    with patch("engine.indicators.compute.get_indicator", return_value=mock_rsi_fn):
        engine = StrategyEngine()
        result = engine.generate_signals(strategy, ohlcv_df)

    assert "signal" in result.columns
    assert "rsi_14" in result.columns
    assert result["signal"].iloc[10] == 1    # entry at cross_above
    assert result["signal"].iloc[20] == -1   # exit at cross_below
    # Unaffected bars should be 0
    assert result["signal"].iloc[5] == 0
    assert result["signal"].iloc[15] == 0


def test_generate_signals_risk_columns(ohlcv_df):
    """Risk management columns are added when stop/take-profit are set."""
    rsi_series = pd.Series(np.full(len(ohlcv_df), 50.0), index=ohlcv_df.index)

    with patch("engine.indicators.compute.get_indicator", return_value=lambda df, **kw: rsi_series):
        engine = StrategyEngine()
        result = engine.generate_signals(
            StrategyDefinition(
                name="Risk Test",
                markets=["us_stock"],
                indicators=[IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14")],
                entry=ConditionGroup(
                    logic="and",
                    conditions=[Condition(left="rsi_14", op=ConditionOp.gt, right=30)],
                ),
                exit=ConditionGroup(
                    logic="or",
                    conditions=[Condition(left="rsi_14", op=ConditionOp.lt, right=70)],
                ),
                risk=RiskParams(stop_loss_pct=0.05, take_profit_pct=0.10),
            ),
            ohlcv_df,
        )

    assert "stop_loss_price" in result.columns
    assert "take_profit_price" in result.columns
    # entry 행(signal=1)만 SL/TP 값을 가짐, exit/hold는 NaN
    entry_rows = result[result["signal"] == 1]
    non_entry_rows = result[result["signal"] != 1]
    if len(entry_rows) > 0:
        row = entry_rows.iloc[0]
        assert row["stop_loss_price"] == pytest.approx(row["close"] * 0.95)
        assert row["take_profit_price"] == pytest.approx(row["close"] * 1.10)
    if len(non_entry_rows) > 0:
        assert non_entry_rows["stop_loss_price"].isna().all()
        assert non_entry_rows["take_profit_price"].isna().all()


def test_generate_signals_multi_output_indicator(ohlcv_df):
    """generate_signals handles multi-output indicator (MACD-style dict output)."""
    n = len(ohlcv_df)
    macd_line = pd.Series(np.linspace(-1.0, 1.0, n), index=ohlcv_df.index)
    signal_line = pd.Series(np.zeros(n), index=ohlcv_df.index)

    def mock_macd_fn(df, **kwargs):
        return {"macd": macd_line, "macdsignal": signal_line, "macdhist": macd_line - signal_line}

    strategy = StrategyDefinition(
        name="MACD Test",
        markets=["us_stock"],
        indicators=[
            IndicatorDef(
                name="MACD",
                params={"fastperiod": 12, "slowperiod": 26, "signalperiod": 9},
                output={"macd": "macd_line", "macdsignal": "signal_line", "macdhist": "histogram"},
            )
        ],
        entry=ConditionGroup(
            logic="and",
            conditions=[
                Condition(left="macd_line", op=ConditionOp.crosses_above, right="signal_line")
            ],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[
                Condition(left="macd_line", op=ConditionOp.crosses_below, right="signal_line")
            ],
        ),
        risk=RiskParams(),
    )

    with patch("engine.indicators.compute.get_indicator", return_value=mock_macd_fn):
        engine = StrategyEngine()
        result = engine.generate_signals(strategy, ohlcv_df)

    assert "macd_line" in result.columns
    assert "signal_line" in result.columns
    assert "histogram" in result.columns
    assert "signal" in result.columns
    # macd_line crosses above signal_line (0) once as it goes from negative to positive
    entry_rows = result[result["signal"] == 1]
    assert len(entry_rows) == 1


def test_generate_signals_no_signals(ohlcv_df):
    """When conditions are never met, all signals should be 0."""
    # RSI always at 50, never crossing above 30 or below 70 (no actual cross)
    rsi_series = pd.Series(np.full(len(ohlcv_df), 50.0), index=ohlcv_df.index)

    strategy = StrategyDefinition(
        name="No Signal Test",
        markets=["us_stock"],
        indicators=[IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14")],
        entry=ConditionGroup(
            logic="and",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_above, right=30)],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_below, right=70)],
        ),
        risk=RiskParams(),
    )

    with patch("engine.indicators.compute.get_indicator", return_value=lambda df, **kw: rsi_series):
        engine = StrategyEngine()
        result = engine.generate_signals(strategy, ohlcv_df)

    assert (result["signal"] == 0).all()

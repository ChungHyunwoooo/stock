"""Shared pytest fixtures for all test modules."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out talib before any engine imports so tests run without ta-lib installed.
# engine/indicators/registry.py does `import talib.abstract as ta` at module level.
# Only mock if talib is NOT actually installed.
# ---------------------------------------------------------------------------
try:
    import talib as _talib_real  # noqa: F401
except ImportError:
    _talib_mock = MagicMock()
    sys.modules.setdefault("talib", _talib_mock)
    sys.modules.setdefault("talib.abstract", _talib_mock)

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


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """50-row OHLCV DataFrame with deterministic values."""
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100.0, 150.0, n)
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


@pytest.fixture
def sample_strategy() -> StrategyDefinition:
    """Minimal single-indicator strategy for use in tests."""
    return StrategyDefinition(
        name="Test RSI Strategy",
        version="1.0",
        status=StrategyStatus.testing,
        markets=["us_stock"],
        indicators=[
            IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14"),
        ],
        entry=ConditionGroup(
            logic="and",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_above, right=30)],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_below, right=70)],
        ),
        risk=RiskParams(stop_loss_pct=0.03, take_profit_pct=0.09, risk_per_trade_pct=0.02),
    )

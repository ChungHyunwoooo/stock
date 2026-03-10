
from unittest.mock import patch

import numpy as np
import pandas as pd

from engine.application.trading import DefinitionSignalGenerator
from engine.schema import Condition, ConditionGroup, ConditionOp, IndicatorDef, RiskParams, StrategyDefinition

def make_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=20, freq="D")
    close = np.linspace(100.0, 120.0, 20)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(20) * 1000,
        },
        index=index,
    )

def test_definition_signal_generator_returns_entry_signal():
    df = make_df()
    rsi_values = pd.Series(np.full(len(df), 35.0), index=df.index)
    rsi_values.iloc[-2] = 29.0
    rsi_values.iloc[-1] = 31.0

    strategy = StrategyDefinition(
        name="RSI Entry",
        markets=["crypto_spot"],
        indicators=[IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14")],
        entry=ConditionGroup(
            logic="and",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_above, right=30)],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[Condition(left="rsi_14", op=ConditionOp.crosses_below, right=70)],
        ),
        risk=RiskParams(stop_loss_pct=0.03, take_profit_pct=0.06),
    )

    with patch("engine.indicators.compute.get_indicator", return_value=lambda _df, **_kw: rsi_values):
        generator = DefinitionSignalGenerator()
        signal = generator.generate(strategy, df, "BTC/USDT")

    assert signal is not None
    assert signal.symbol == "BTC/USDT"
    assert signal.action.value == "entry"
    assert signal.side.value == "long"
    assert signal.stop_loss is not None
    assert signal.take_profits

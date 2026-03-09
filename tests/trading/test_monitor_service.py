from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from engine.application.trading import StrategyMonitorService, TradingOrchestrator
from engine.infrastructure.execution import PaperBroker
from engine.infrastructure.notifications import MemoryNotifier
from engine.infrastructure.runtime import JsonRuntimeStore
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


def test_monitor_service_evaluates_strategy_and_routes_signal(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    orchestrator = TradingOrchestrator(store, notifier, broker)
    monitor = StrategyMonitorService(orchestrator)
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

    mock_provider = type("MockProvider", (), {"fetch_ohlcv": lambda self, *args, **kwargs: df})()

    with (
        patch("engine.application.trading.monitor.get_provider", return_value=mock_provider),
        patch("engine.indicators.compute.get_indicator", return_value=lambda _df, **_kw: rsi_values),
    ):
        signal = monitor.evaluate_strategy(
            strategy,
            symbol="BTC/USDT",
            start="2024-01-01",
            end="2024-01-31",
            execute=True,
        )

    state = store.load()
    assert signal is not None
    assert signal.symbol == "BTC/USDT"
    assert len(state.executions) == 0
    assert len(notifier.signals) == 1

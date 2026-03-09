"""Integration tests — end-to-end flows across store, backtest, and schema."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine.schema import StrategyDefinition
from engine.store.database import get_engine, get_session, init_db
from engine.store.models import BacktestRecord
from engine.store.repository import BacktestRepository, StrategyRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STRATEGY_JSON_PATH = Path(__file__).parent.parent / "strategies" / "active" / "momentum_rsi_macd_v1.json"

_IN_MEMORY_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_engine():
    """Reset the module-level singleton between tests."""
    import engine.store.database as db_module
    original = db_module._engine
    db_module._engine = None
    yield
    db_module._engine = original


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    get_engine(url)
    init_db(url)
    return url


@pytest.fixture
def strategy() -> StrategyDefinition:
    data = json.loads(STRATEGY_JSON_PATH.read_text())
    return StrategyDefinition.model_validate(data)


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100.0, 160.0, n)
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


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_example_strategy_json_validates():
    """The example strategy JSON must be schema-valid."""
    data = json.loads(STRATEGY_JSON_PATH.read_text())
    strategy = StrategyDefinition.model_validate(data)
    assert strategy.name == "RSI + MACD Momentum"
    assert len(strategy.indicators) == 2
    assert len(strategy.entry.conditions) == 2
    assert len(strategy.exit.conditions) == 2


# ---------------------------------------------------------------------------
# Store round-trip
# ---------------------------------------------------------------------------


def test_strategy_store_round_trip(db_url, strategy):
    """Save a strategy to the DB and retrieve it by ID."""
    repo = StrategyRepository()
    with get_session() as session:
        record = repo.save(session, strategy)
        record_id = record.id

    with get_session() as session:
        fetched = repo.get(session, record_id)
        assert fetched is not None
        assert fetched.name == strategy.name
        assert fetched.version == strategy.version
        assert fetched.status == strategy.status.value


def test_strategy_list_with_status_filter(db_url, strategy):
    """list_all filters correctly by status."""
    repo = StrategyRepository()
    with get_session() as session:
        repo.save(session, strategy)

    with get_session() as session:
        all_records = repo.list_all(session)
        testing_records = repo.list_all(session, status="testing")
        draft_records = repo.list_all(session, status="draft")

    assert len(all_records) == 1
    assert len(testing_records) == 1
    assert len(draft_records) == 0


def test_strategy_update_status(db_url, strategy):
    """update_status persists the new status."""
    repo = StrategyRepository()
    with get_session() as session:
        record = repo.save(session, strategy)
        record_id = record.id

    with get_session() as session:
        repo.update_status(session, record_id, "active")

    with get_session() as session:
        fetched = repo.get(session, record_id)
        assert fetched is not None
        assert fetched.status == "active"


def test_strategy_delete(db_url, strategy):
    """Deleted strategies are no longer retrievable."""
    repo = StrategyRepository()
    with get_session() as session:
        record = repo.save(session, strategy)
        record_id = record.id

    with get_session() as session:
        repo.delete(session, record_id)

    with get_session() as session:
        assert repo.get(session, record_id) is None
        assert repo.list_all(session) == []


def test_backtest_store_round_trip(db_url, strategy):
    """Save a backtest record linked to a strategy and retrieve it."""
    s_repo = StrategyRepository()
    b_repo = BacktestRepository()

    with get_session() as session:
        s_record = s_repo.save(session, strategy)
        b_record = BacktestRecord(
            strategy_id=s_record.id,
            symbol="AAPL",
            timeframe="1d",
            start_date="2024-01-01",
            end_date="2024-06-30",
            total_return=0.15,
            sharpe_ratio=1.23,
            max_drawdown=-0.08,
            result_json='{"trades": []}',
        )
        saved = b_repo.save(session, b_record)
        backtest_id = saved.id
        strategy_id = s_record.id

    with get_session() as session:
        fetched = b_repo.get(session, backtest_id)
        assert fetched is not None
        assert fetched.symbol == "AAPL"
        assert fetched.total_return == pytest.approx(0.15)

        by_strategy = b_repo.get_by_strategy(session, strategy_id)
        assert len(by_strategy) == 1


# ---------------------------------------------------------------------------
# Backtest runner integration (mocked data provider)
# ---------------------------------------------------------------------------


def test_backtest_runner_produces_result(strategy):
    """BacktestRunner returns a well-formed result with mocked OHLCV data."""
    from engine.backtest.runner import BacktestRunner

    ohlcv = _make_ohlcv(60)

    mock_provider = type("MockProvider", (), {"fetch_ohlcv": lambda self, *a, **kw: ohlcv})()

    rsi_series = pd.Series(np.full(60, 50.0), index=ohlcv.index)
    macd_line = pd.Series(np.linspace(-1.0, 1.0, 60), index=ohlcv.index)
    signal_line = pd.Series(np.zeros(60), index=ohlcv.index)

    def mock_rsi(df, **kwargs):
        return rsi_series

    def mock_macd(df, **kwargs):
        return {"macd": macd_line, "macdsignal": signal_line, "macdhist": macd_line - signal_line}

    def mock_get_indicator(name):
        if name.upper() == "MACD":
            return mock_macd
        return mock_rsi

    with (
        patch("engine.data.base.get_provider", return_value=mock_provider),
        patch("engine.indicators.compute.get_indicator", side_effect=mock_get_indicator),
    ):
        runner = BacktestRunner()
        result = runner.run(strategy, "AAPL", "2024-01-01", "2024-03-01", "1d", 10_000.0)

    assert result.symbol == "AAPL"
    assert result.initial_capital == 10_000.0
    assert isinstance(result.total_return, float)
    assert len(result.equity_curve) > 0
    result_data = json.loads(result.to_result_json())
    assert "total_return" in result_data
    assert "num_trades" in result_data


def test_backtest_metrics_no_trades():
    """BacktestRunner handles zero-signal data gracefully."""
    from engine.backtest.runner import BacktestRunner
    from engine.schema import Condition, ConditionGroup, ConditionOp, IndicatorDef, RiskParams

    # Strategy whose conditions are never met (impossible threshold)
    impossible_strategy = StrategyDefinition(
        name="Never Trades",
        markets=["us_stock"],
        indicators=[IndicatorDef(name="RSI", params={"timeperiod": 14}, output="rsi_14")],
        entry=ConditionGroup(
            logic="and",
            conditions=[Condition(left="rsi_14", op=ConditionOp.gt, right=200)],
        ),
        exit=ConditionGroup(
            logic="or",
            conditions=[Condition(left="rsi_14", op=ConditionOp.lt, right=-10)],
        ),
        risk=RiskParams(),
    )

    ohlcv = _make_ohlcv(30)
    rsi_series = pd.Series(np.full(30, 50.0), index=ohlcv.index)
    mock_provider = type("MockProvider", (), {"fetch_ohlcv": lambda self, *a, **kw: ohlcv})()

    with (
        patch("engine.data.base.get_provider", return_value=mock_provider),
        patch("engine.indicators.compute.get_indicator", return_value=lambda df, **kw: rsi_series),
    ):
        runner = BacktestRunner()
        result = runner.run(impossible_strategy, "AAPL", "2024-01-01", "2024-02-01")

    assert len(result.trades) == 0
    assert result.total_return == 0.0
    assert result.final_capital == result.initial_capital

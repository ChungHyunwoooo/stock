"""Tests for backtest interfaces: API endpoints + CLI rich table."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import BacktestRecord, Base, StrategyRecord
from engine.core.repository import BacktestRepository


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    yield sess
    sess.close()


@pytest.fixture()
def strategy_id(session: Session) -> int:
    rec = StrategyRecord(
        name="test_strat", version="1.0", status="draft", definition_json="{}"
    )
    session.add(rec)
    session.flush()
    return rec.id


@pytest.fixture()
def strategy_id_2(session: Session) -> int:
    rec = StrategyRecord(
        name="test_strat_2", version="1.0", status="draft", definition_json="{}"
    )
    session.add(rec)
    session.flush()
    return rec.id


def _make_record(strategy_id: int, **overrides) -> BacktestRecord:
    defaults = dict(
        strategy_id=strategy_id,
        symbol="BTC/USDT",
        timeframe="1d",
        start_date="2025-01-01",
        end_date="2025-03-01",
        total_return=0.15,
        sharpe_ratio=1.2,
        max_drawdown=-0.08,
        result_json='{"trades": []}',
        slippage_model="NoSlippage",
        fee_rate=0.001,
    )
    defaults.update(overrides)
    return BacktestRecord(**defaults)


@pytest.fixture()
def populated_session(session, strategy_id, strategy_id_2):
    """Insert test backtest records for both strategies."""
    for i in range(3):
        session.add(_make_record(strategy_id, total_return=0.1 * (i + 1), symbol=f"SYM{i}"))
    session.add(_make_record(strategy_id_2, total_return=0.5, symbol="ETH/USDT"))
    session.flush()
    return session


@pytest.fixture()
def client(populated_session):
    """FastAPI TestClient with patched DB dependency."""
    from api.routers.backtests import router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield populated_session

    from api.dependencies import get_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# -- API Tests ---------------------------------------------------------------


class TestAPIHistory:
    """GET /backtests/{strategy_id}/history endpoint."""

    def test_history_returns_list(self, client, strategy_id):
        resp = client.get(f"/backtests/{strategy_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_history_with_limit(self, client, strategy_id):
        resp = client.get(f"/backtests/{strategy_id}/history?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_history_empty_strategy(self, client):
        resp = client.get("/backtests/9999/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_has_phase2_fields(self, client, strategy_id):
        resp = client.get(f"/backtests/{strategy_id}/history")
        data = resp.json()
        assert len(data) > 0
        record = data[0]
        assert "slippage_model" in record
        assert "fee_rate" in record


class TestAPICompare:
    """GET /backtests/compare endpoint."""

    def test_compare_returns_list(self, client, strategy_id, strategy_id_2):
        resp = client.get(f"/backtests/compare?strategy_ids={strategy_id},{strategy_id_2}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 4  # 3 from strategy 1 + 1 from strategy 2

    def test_compare_single_strategy(self, client, strategy_id):
        resp = client.get(f"/backtests/compare?strategy_ids={strategy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3


class TestAPIDelete:
    """DELETE endpoints."""

    def test_delete_single(self, client, populated_session):
        # Get first record id
        records = BacktestRepository().list_all(populated_session)
        rec_id = records[0].id

        resp = client.delete(f"/backtests/{rec_id}")
        assert resp.status_code == 204

    def test_delete_nonexistent(self, client):
        resp = client.delete("/backtests/99999")
        assert resp.status_code == 404

    def test_delete_by_strategy(self, client, strategy_id, populated_session):
        resp = client.delete(f"/backtests/strategy/{strategy_id}")
        assert resp.status_code == 204

        remaining = BacktestRepository().get_by_strategy(populated_session, strategy_id)
        assert remaining == []


# -- CLI Tests ---------------------------------------------------------------


class TestCLI:
    """CLI show_history and compare_strategies functions."""

    def test_show_history_returns_dicts(self, session, strategy_id):
        for i in range(3):
            session.add(_make_record(strategy_id, total_return=0.1 * (i + 1)))
        session.flush()

        from contextlib import contextmanager

        @contextmanager
        def mock_get_session():
            yield session

        with patch("engine.backtest.history_cli.get_session", mock_get_session):
            from engine.backtest.history_cli import show_history

            result = show_history(strategy_id, limit=20)

        assert isinstance(result, list)
        assert len(result) == 3
        assert "total_return" in result[0]

    def test_compare_strategies_returns_dicts(self, session, strategy_id, strategy_id_2):
        session.add(_make_record(strategy_id, total_return=0.2))
        session.add(_make_record(strategy_id_2, total_return=0.5))
        session.flush()

        from contextlib import contextmanager

        @contextmanager
        def mock_get_session():
            yield session

        with patch("engine.backtest.history_cli.get_session", mock_get_session):
            from engine.backtest.history_cli import compare_strategies

            result = compare_strategies([strategy_id, strategy_id_2])

        assert isinstance(result, list)
        assert len(result) == 2
        strategy_ids_returned = {r["strategy_id"] for r in result}
        assert strategy_id in strategy_ids_returned
        assert strategy_id_2 in strategy_ids_returned

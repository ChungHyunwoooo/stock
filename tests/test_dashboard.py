"""DashboardDataService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.interfaces.dashboard.data_service import DashboardDataService


@pytest.fixture
def service() -> DashboardDataService:
    """Create DashboardDataService with mocked dependencies."""
    with (
        patch("engine.interfaces.dashboard.data_service.LifecycleManager") as MockLM,
        patch("engine.interfaces.dashboard.data_service.TradeRepository") as MockTR,
        patch("engine.interfaces.dashboard.data_service.JsonRuntimeStore") as MockJRS,
    ):
        svc = DashboardDataService()
        svc._lifecycle = MockLM.return_value
        svc._trade_repo = MockTR.return_value
        svc._runtime_store = MockJRS.return_value
        yield svc


class TestLifecycleData:
    def test_lifecycle_summary_returns_all_strategies(self, service: DashboardDataService) -> None:
        strategies = [
            {"id": "s1", "name": "RSI", "status": "active"},
            {"id": "s2", "name": "EMA", "status": "draft"},
            {"id": "s3", "name": "BB", "status": "active"},
        ]
        service._lifecycle.list_by_status.return_value = strategies

        result = service.get_lifecycle_summary()

        service._lifecycle.list_by_status.assert_called_once_with(None)
        assert result == strategies
        assert len(result) == 3

    def test_lifecycle_counts_groups_by_status(self, service: DashboardDataService) -> None:
        strategies = [
            {"id": "s1", "status": "active"},
            {"id": "s2", "status": "draft"},
            {"id": "s3", "status": "active"},
            {"id": "s4", "status": "paper"},
        ]
        service._lifecycle.list_by_status.return_value = strategies

        counts = service.get_lifecycle_counts()

        assert counts == {"active": 2, "draft": 1, "paper": 1}


class TestPortfolioData:
    def test_portfolio_summary(self, service: DashboardDataService) -> None:
        session = MagicMock()
        service._trade_repo.summary.return_value = {
            "total": 10,
            "wins": 6,
            "losses": 4,
            "win_rate": 60.0,
            "total_profit": 1500.0,
            "avg_profit_pct": 2.5,
            "best_trade": 10.0,
            "worst_trade": -5.0,
        }

        result = service.get_portfolio_summary(session)

        service._trade_repo.summary.assert_called_once_with(session)
        assert result["total"] == 10
        assert result["win_rate"] == 60.0
        assert result["total_profit"] == 1500.0

    def test_strategy_pnl(self, service: DashboardDataService) -> None:
        session = MagicMock()
        service._trade_repo.summary.return_value = {
            "total": 5,
            "wins": 3,
            "win_rate": 60.0,
            "total_profit": 500.0,
        }

        result = service.get_strategy_pnl(session, "rsi_strat")

        service._trade_repo.summary.assert_called_once_with(
            session, strategy_name="rsi_strat"
        )
        assert result["total"] == 5


class TestSystemHealth:
    def test_system_health_returns_runtime_state(self, service: DashboardDataService) -> None:
        mock_state = MagicMock()
        mock_state.mode.value = "paper_trading"
        mock_state.paused = False
        mock_state.paused_strategies = {"s1", "s2"}
        mock_state.updated_at = "2026-03-12T00:00:00Z"
        service._runtime_store.load.return_value = mock_state

        result = service.get_system_health()

        assert result["mode"] == "paper_trading"
        assert result["paused"] is False
        assert result["paused_strategies"] == {"s1", "s2"}
        assert result["updated_at"] == "2026-03-12T00:00:00Z"


class TestPositionsAndTrades:
    def test_open_positions(self, service: DashboardDataService) -> None:
        session = MagicMock()
        mock_trade = MagicMock()
        mock_trade.symbol = "BTCUSDT"
        mock_trade.side = "long"
        mock_trade.entry_price = 50000.0
        mock_trade.entry_quantity = 0.1
        mock_trade.stop_loss = 49000.0
        mock_trade.take_profit = 52000.0
        mock_trade.entry_at = "2026-03-12T00:00:00Z"
        mock_trade.strategy_name = "rsi_strat"
        service._trade_repo.list_open.return_value = [mock_trade]

        result = service.get_open_positions(session)

        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[0]["entry_price"] == 50000.0

    def test_closed_trades(self, service: DashboardDataService) -> None:
        session = MagicMock()
        mock_trade = MagicMock()
        mock_trade.trade_id = "t1"
        mock_trade.symbol = "ETHUSDT"
        mock_trade.side = "long"
        mock_trade.strategy_name = "ema_strat"
        mock_trade.entry_price = 3000.0
        mock_trade.exit_price = 3100.0
        mock_trade.entry_quantity = 1.0
        mock_trade.profit_abs = 100.0
        mock_trade.profit_pct = 3.33
        mock_trade.entry_at = "2026-03-11T00:00:00Z"
        mock_trade.exit_at = "2026-03-12T00:00:00Z"
        mock_trade.exit_reason = "take_profit"
        mock_trade.duration_seconds = 86400
        service._trade_repo.list_closed.return_value = [mock_trade]

        result = service.get_closed_trades(session, limit=50)

        service._trade_repo.list_closed.assert_called_once_with(session, limit=50)
        assert len(result) == 1
        assert result[0]["pnl"] == 100.0

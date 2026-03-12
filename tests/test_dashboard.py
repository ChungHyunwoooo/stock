"""DashboardDataService unit tests."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
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


class TestSweepProgress:
    def test_sweep_progress_returns_status_when_file_exists(self) -> None:
        """sweep_status.json이 존재하면 딕셔너리 반환."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir()
            status_data = {
                "completed": 5,
                "total": 20,
                "best_sharpe": 1.23,
                "candidates_found": 2,
                "updated_at": "2026-03-12T00:00:00Z",
            }
            (state_dir / "sweep_status.json").write_text(
                json.dumps(status_data), encoding="utf-8"
            )

            svc = DashboardDataService.__new__(DashboardDataService)
            result = svc.get_sweep_status(state_dir=state_dir)

            assert result is not None
            assert result["completed"] == 5
            assert result["total"] == 20
            assert result["best_sharpe"] == 1.23
            assert result["candidates_found"] == 2

    def test_sweep_progress_returns_none_when_no_file(self) -> None:
        """sweep_status.json이 없으면 None 반환."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir()

            svc = DashboardDataService.__new__(DashboardDataService)
            result = svc.get_sweep_status(state_dir=state_dir)

            assert result is None


class TestConfigEdit:
    def test_config_edit_atomic_write(self) -> None:
        """definition.json atomic write 후 변경 값 반영, 원본 미손상."""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir) / "strategies" / "test_strat"
            strategy_dir.mkdir(parents=True)
            original = {
                "name": "test_strat",
                "risk": {"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
            }
            def_path = strategy_dir / "definition.json"
            def_path.write_text(json.dumps(original), encoding="utf-8")

            # Modify risk params
            updated = json.loads(def_path.read_text(encoding="utf-8"))
            updated["risk"]["stop_loss_pct"] = 3.0

            # Atomic write: tempfile + rename
            tmp_path = def_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(def_path))

            # Verify
            result = json.loads(def_path.read_text(encoding="utf-8"))
            assert result["risk"]["stop_loss_pct"] == 3.0
            assert result["risk"]["take_profit_pct"] == 4.0
            assert result["name"] == "test_strat"


class TestSweepStatusWriter:
    def test_write_sweep_status_creates_file(self) -> None:
        """_write_sweep_status 호출 시 sweep_status.json에 올바른 JSON 기록."""
        from engine.strategy.indicator_sweeper import IndicatorSweeper

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            # state dir 없는 상태에서 시작 -- 메서드가 생성해야 함

            sweeper = IndicatorSweeper.__new__(IndicatorSweeper)
            sweeper._write_sweep_status(
                completed=3,
                total=10,
                best_sharpe=1.5,
                candidates_found=1,
                state_dir=state_dir,
            )

            status_path = state_dir / "sweep_status.json"
            assert status_path.exists()

            data = json.loads(status_path.read_text(encoding="utf-8"))
            assert data["completed"] == 3
            assert data["total"] == 10
            assert data["best_sharpe"] == 1.5
            assert data["candidates_found"] == 1
            assert "updated_at" in data

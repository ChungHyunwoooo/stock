"""Bootstrap assembly tests -- TradingRuntime with full component wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime


class TestTradingRuntimeConfig:
    """TradingRuntimeConfig default and custom values."""

    def test_runtime_config_defaults(self):
        cfg = TradingRuntimeConfig()
        assert cfg.monitor_interval == 900
        assert cfg.monitor_warning_threshold == 0.15
        assert cfg.monitor_critical_sharpe == -0.5
        assert cfg.correlation_threshold == 0.7
        assert cfg.correlation_window == 100
        assert cfg.default_kelly_fraction == 0.25
        assert cfg.min_trades_for_kelly == 20

    def test_runtime_config_custom(self):
        cfg = TradingRuntimeConfig(
            monitor_interval=300,
            correlation_threshold=0.5,
            default_kelly_fraction=0.5,
            min_trades_for_kelly=10,
        )
        assert cfg.monitor_interval == 300
        assert cfg.correlation_threshold == 0.5
        assert cfg.default_kelly_fraction == 0.5
        assert cfg.min_trades_for_kelly == 10


class TestBuildTradingRuntime:
    """build_trading_runtime() assembles all components."""

    @patch("engine.interfaces.bootstrap.runtime_store_plugins")
    @patch("engine.interfaces.bootstrap.notifier_plugins")
    @patch("engine.interfaces.bootstrap.broker_plugins")
    def test_build_runtime_assembles_all_components(
        self, mock_broker_plugins, mock_notifier_plugins, mock_store_plugins,
    ):
        mock_store_plugins.create.return_value = MagicMock()
        mock_notifier_plugins.create.return_value = MagicMock()
        mock_broker_plugins.create.return_value = MagicMock()

        with (
            patch("engine.core.repository.TradeRepository") as mock_trade_repo,
            patch("engine.core.repository.BacktestRepository") as mock_bt_repo,
            patch("engine.strategy.lifecycle_manager.LifecycleManager") as mock_lifecycle,
            patch("engine.strategy.risk_manager.RiskManager") as mock_risk_mgr,
            patch("engine.strategy.performance_monitor.StrategyPerformanceMonitor") as mock_monitor_cls,
            patch("engine.core.database.get_session") as mock_get_session,
        ):
            mock_monitor = MagicMock()
            mock_monitor_cls.return_value = mock_monitor
            mock_monitor.run_daemon.return_value = MagicMock()

            runtime = build_trading_runtime()

            assert runtime.orchestrator is not None
            assert runtime.orchestrator.portfolio_risk is not None
            assert runtime.position_sizer is not None
            assert runtime.portfolio_risk is not None
            assert runtime.performance_monitor is not None
            mock_monitor.run_daemon.assert_called_once()

    @patch("engine.interfaces.bootstrap.runtime_store_plugins")
    @patch("engine.interfaces.bootstrap.notifier_plugins")
    @patch("engine.interfaces.bootstrap.broker_plugins")
    def test_build_runtime_passes_config_to_monitor(
        self, mock_broker_plugins, mock_notifier_plugins, mock_store_plugins,
    ):
        mock_store_plugins.create.return_value = MagicMock()
        mock_notifier_plugins.create.return_value = MagicMock()
        mock_broker_plugins.create.return_value = MagicMock()

        with (
            patch("engine.core.repository.TradeRepository"),
            patch("engine.core.repository.BacktestRepository"),
            patch("engine.strategy.lifecycle_manager.LifecycleManager"),
            patch("engine.strategy.risk_manager.RiskManager"),
            patch("engine.strategy.performance_monitor.StrategyPerformanceMonitor") as mock_monitor_cls,
            patch("engine.core.database.get_session"),
        ):
            mock_monitor = MagicMock()
            mock_monitor_cls.return_value = mock_monitor
            mock_monitor.run_daemon.return_value = MagicMock()

            cfg = TradingRuntimeConfig(monitor_interval=60, monitor_warning_threshold=0.3)
            runtime = build_trading_runtime(cfg)

            # Check PerformanceConfig passed to monitor constructor
            call_kwargs = mock_monitor_cls.call_args
            perf_config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert perf_config.check_interval_seconds == 60
            assert perf_config.warning_threshold == 0.3


from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from engine.application.trading.trading_control import TradingControlService
from engine.application.trading.orchestrator import TradingOrchestrator
from engine.strategy.plugin_runtime import broker_plugins, notifier_plugins, runtime_store_plugins

if TYPE_CHECKING:
    from engine.strategy.performance_monitor import StrategyPerformanceMonitor
    from engine.strategy.portfolio_risk import PortfolioRiskManager
    from engine.strategy.position_sizer import PositionSizer


@dataclass(slots=True)
class TradingRuntimeConfig:
    # Existing
    state_path: str | Path = "state/runtime_state.json"
    broker_plugin: str = "paper"
    notifier_plugin: str = "discord_webhook"
    runtime_store_plugin: str = "json"
    discord_config_path: str | Path = "config/discord.json"
    # Phase 9: Monitor
    monitor_interval: int = 900
    monitor_warning_threshold: float = 0.15
    monitor_critical_sharpe: float = -0.5
    # Phase 9: Risk
    correlation_threshold: float = 0.7
    correlation_window: int = 100
    # Phase 9: Sizer
    default_kelly_fraction: float = 0.25
    min_trades_for_kelly: int = 20


@dataclass(slots=True)
class TradingRuntime:
    orchestrator: TradingOrchestrator
    control: TradingControlService
    config: TradingRuntimeConfig
    position_sizer: PositionSizer
    portfolio_risk: PortfolioRiskManager
    performance_monitor: StrategyPerformanceMonitor


def build_trading_runtime(config: TradingRuntimeConfig | None = None) -> TradingRuntime:
    from engine.core.database import get_session
    from engine.core.repository import TradeRepository, BacktestRepository
    from engine.strategy.lifecycle_manager import LifecycleManager
    from engine.strategy.performance_monitor import StrategyPerformanceMonitor, PerformanceConfig
    from engine.strategy.position_sizer import PositionSizer
    from engine.strategy.portfolio_risk import PortfolioRiskManager, PortfolioRiskConfig
    from engine.strategy.risk_manager import RiskManager

    runtime_config = config or TradingRuntimeConfig()

    # -- Plugin-based components (existing) --
    store = runtime_store_plugins.create(
        runtime_config.runtime_store_plugin,
        state_path=runtime_config.state_path,
    )
    notifier = notifier_plugins.create(
        runtime_config.notifier_plugin,
        config_path=runtime_config.discord_config_path,
    )
    broker = broker_plugins.create(runtime_config.broker_plugin)

    # -- Phase 4/5/9: Risk + Sizing components --
    risk_manager = RiskManager()
    position_sizer = PositionSizer(
        risk_manager=risk_manager,
        default_kelly_fraction=runtime_config.default_kelly_fraction,
        min_trades_for_kelly=runtime_config.min_trades_for_kelly,
    )
    portfolio_risk_config = PortfolioRiskConfig(
        correlation_threshold=runtime_config.correlation_threshold,
        correlation_window=runtime_config.correlation_window,
    )
    portfolio_risk = PortfolioRiskManager(
        config=portfolio_risk_config,
        notifier=notifier,
    )

    # -- Orchestrator with position_sizer + portfolio_risk injected --
    orchestrator = TradingOrchestrator(
        store, notifier, broker,
        position_sizer=position_sizer,
        portfolio_risk=portfolio_risk,
    )
    control = TradingControlService(store, notifier, broker)

    # -- Phase 5/9: Performance monitor + daemon --
    trade_repo = TradeRepository()
    backtest_repo = BacktestRepository()
    lifecycle = LifecycleManager()
    perf_config = PerformanceConfig(
        check_interval_seconds=runtime_config.monitor_interval,
        warning_threshold=runtime_config.monitor_warning_threshold,
        critical_sharpe=runtime_config.monitor_critical_sharpe,
    )
    performance_monitor = StrategyPerformanceMonitor(
        trade_repo=trade_repo,
        backtest_repo=backtest_repo,
        lifecycle=lifecycle,
        runtime_store=store,
        notifier=notifier,
        config=perf_config,
    )
    performance_monitor.run_daemon(session_factory=get_session)

    return TradingRuntime(
        orchestrator=orchestrator,
        control=control,
        config=runtime_config,
        position_sizer=position_sizer,
        portfolio_risk=portfolio_risk,
        performance_monitor=performance_monitor,
    )

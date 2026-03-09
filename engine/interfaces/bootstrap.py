from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.application.trading.control import TradingControlService
from engine.application.trading.orchestrator import TradingOrchestrator
from engine.plugins import broker_plugins, notifier_plugins, runtime_store_plugins


@dataclass(slots=True)
class TradingRuntimeConfig:
    state_path: str | Path = "config/runtime_state.json"
    broker_plugin: str = "paper"
    notifier_plugin: str = "discord_webhook"
    runtime_store_plugin: str = "json"
    discord_config_path: str | Path = "config/discord.json"


@dataclass(slots=True)
class TradingRuntime:
    orchestrator: TradingOrchestrator
    control: TradingControlService
    config: TradingRuntimeConfig


def build_trading_runtime(config: TradingRuntimeConfig | None = None) -> TradingRuntime:
    runtime_config = config or TradingRuntimeConfig()
    store = runtime_store_plugins.create(
        runtime_config.runtime_store_plugin,
        state_path=runtime_config.state_path,
    )
    notifier = notifier_plugins.create(
        runtime_config.notifier_plugin,
        config_path=runtime_config.discord_config_path,
    )
    broker = broker_plugins.create(runtime_config.broker_plugin)
    orchestrator = TradingOrchestrator(store, notifier, broker)
    control = TradingControlService(store, notifier, broker)
    return TradingRuntime(orchestrator=orchestrator, control=control, config=runtime_config)

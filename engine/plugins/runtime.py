from __future__ import annotations

from pathlib import Path

from engine.application.trading.providers import JsonStrategySource
from engine.application.trading.providers.base import StrategySourcePort
from engine.domain.trading.ports import BrokerPort, NotificationPort, RuntimeStorePort
from engine.infrastructure.execution import PaperBroker
from engine.infrastructure.notifications import DiscordWebhookNotifier, MemoryNotifier
from engine.infrastructure.runtime import JsonRuntimeStore
from engine.plugins.registry import PluginRegistry

broker_plugins = PluginRegistry[BrokerPort]("broker")
notifier_plugins = PluginRegistry[NotificationPort]("notifier")
runtime_store_plugins = PluginRegistry[RuntimeStorePort]("runtime_store")
strategy_source_plugins = PluginRegistry[StrategySourcePort]("strategy_source")


broker_plugins.register("paper", lambda **_: PaperBroker(), "Paper trading broker")
notifier_plugins.register(
    "discord_webhook",
    lambda config_path="config/discord.json", **_: DiscordWebhookNotifier(config_path=config_path),
    "Discord webhook notifier",
)
notifier_plugins.register("memory", lambda **_: MemoryNotifier(), "In-memory notifier for tests")
runtime_store_plugins.register(
    "json",
    lambda state_path="config/runtime_state.json", **_: JsonRuntimeStore(Path(state_path)),
    "JSON runtime state store",
)
strategy_source_plugins.register(
    "json_definition",
    lambda **_: JsonStrategySource(),
    "JSON strategy definition source",
)

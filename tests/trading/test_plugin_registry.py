
import discord

from engine.notifications import MemoryNotifier
from engine.interfaces.discord.context import DiscordBotContext
from engine.interfaces.discord.registry import register_default_commands
from engine.strategy.plugin_runtime import broker_plugins, notifier_plugins, runtime_store_plugins, strategy_source_plugins

class DummyControl:
    def get_state(self):
        class State:
            mode = type("Mode", (), {"value": "alert_only"})()
            paused = False
            automation_enabled = True
            broker = type("Broker", (), {"value": "paper"})()
            pending_orders = []
            positions = []
            executions = []

        return State()

    def pause(self):
        return self.get_state()

    def resume(self):
        return self.get_state()

    def set_mode(self, _mode):
        return self.get_state()

    def approve_pending(self, _pending_id):
        return self.get_state()

    def reject_pending(self, _pending_id):
        return self.get_state()

def test_runtime_plugin_registries_expose_defaults(tmp_path):
    assert "paper" in broker_plugins.names()
    assert "discord_webhook" in notifier_plugins.names()
    assert "json" in runtime_store_plugins.names()
    assert "json_definition" in strategy_source_plugins.names()

    store = runtime_store_plugins.create("json", state_path=tmp_path / "runtime.json")
    notifier = notifier_plugins.create("memory")
    broker = broker_plugins.create("paper")
    source = strategy_source_plugins.create("json_definition")

    assert store.load().mode.value == "alert_only"
    assert isinstance(notifier, MemoryNotifier)
    assert broker is not None
    assert source is not None

def test_discord_command_registry_registers_all_groups():
    client = discord.Client(intents=discord.Intents.none())
    tree = discord.app_commands.CommandTree(client)
    names = register_default_commands(tree, DiscordBotContext(control=DummyControl()))

    registered = sorted(command.name for command in tree.get_commands())
    assert names == ["runtime", "orders", "analysis", "pattern", "scanner"]
    assert "analysis" in registered
    assert "pattern" in registered

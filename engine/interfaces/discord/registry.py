from __future__ import annotations

from discord import app_commands

from engine.interfaces.discord.commands import DEFAULT_COMMAND_PLUGINS
from engine.interfaces.discord.context import DiscordBotContext


def register_default_commands(tree: app_commands.CommandTree, context: DiscordBotContext) -> list[str]:
    names: list[str] = []
    for plugin in DEFAULT_COMMAND_PLUGINS:
        plugin.register(tree, context)
        names.append(plugin.name)
    return names

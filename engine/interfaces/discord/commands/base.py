from __future__ import annotations

from typing import Protocol

from discord import app_commands

from engine.interfaces.discord.context import DiscordBotContext


class DiscordCommandPlugin(Protocol):
    name: str

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        ...

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

import discord

from engine.application.trading.control import TradingControlService
from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime
from engine.interfaces.discord.context import DiscordBotContext
from engine.interfaces.discord.preferences import DiscordUserPreferenceStore
from engine.interfaces.discord.registry import register_default_commands

logger = logging.getLogger(__name__)
CONFIG_PATH = Path("config/discord.json")

_bot: discord.Client | None = None
_bot_thread: threading.Thread | None = None
_bot_running = False


def _load_bot_token() -> str | None:
    env_token = os.getenv("DISCORD_BOT_TOKEN")
    if env_token:
        return env_token
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text())
    return data.get("bot_token")


def create_bot(control: TradingControlService | None = None) -> discord.Client:
    runtime_control = control or build_trading_runtime(TradingRuntimeConfig()).control
    preferences = DiscordUserPreferenceStore()
    context = DiscordBotContext(control=runtime_control, preferences=preferences)
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    client.runtime_control = runtime_control
    client.user_preferences = preferences
    tree = discord.app_commands.CommandTree(client)
    plugin_names = register_default_commands(tree, context)

    @client.event
    async def on_ready() -> None:
        logger.info("Trading control bot logged in as %s", client.user)
        try:
            # 길드 지정 싱크 (즉시 반영) → 없으면 글로벌 싱크
            guild_id = None
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text())
                gid = data.get("guild_id")
                if gid:
                    guild_id = discord.Object(id=int(gid))

            if guild_id:
                tree.copy_global_to(guild=guild_id)
                await tree.sync(guild=guild_id)
                logger.info("Guild-synced commands: %s", ", ".join(plugin_names))
            else:
                await tree.sync()
                logger.info("Global-synced commands: %s", ", ".join(plugin_names))
        except Exception:
            logger.exception("Failed to sync command tree")

    return client


def run_bot_background(control: TradingControlService | None = None) -> bool:
    global _bot, _bot_thread, _bot_running
    if _bot_running:
        return True

    token = _load_bot_token()
    if not token:
        logger.error("Discord bot token is not configured")
        return False

    client = create_bot(control)

    def _run() -> None:
        global _bot_running
        _bot_running = True
        try:
            asyncio.run(client.start(token))
        except Exception:
            logger.exception("Discord bot crashed")
        finally:
            _bot_running = False

    _bot = client
    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()
    return True


def stop_bot() -> bool:
    global _bot_running
    if not _bot_running or _bot is None:
        _bot_running = False
        return True
    _bot_running = False
    if _bot.loop and _bot.loop.is_running():
        asyncio.run_coroutine_threadsafe(_bot.close(), _bot.loop)
    return True

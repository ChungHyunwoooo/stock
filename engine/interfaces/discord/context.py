from __future__ import annotations

from dataclasses import dataclass, field

from engine.application.trading.control import TradingControlService
from engine.interfaces.discord.preferences import DiscordUserPreferenceStore


@dataclass(slots=True)
class DiscordBotContext:
    control: TradingControlService
    preferences: DiscordUserPreferenceStore = field(default_factory=DiscordUserPreferenceStore)


from dataclasses import dataclass, field

from engine.application.trading.trading_control import TradingControlService
from engine.interfaces.discord.preferences import DiscordUserPreferenceStore
from engine.strategy.lifecycle_manager import LifecycleManager

@dataclass(slots=True)
class DiscordBotContext:
    control: TradingControlService
    preferences: DiscordUserPreferenceStore = field(default_factory=DiscordUserPreferenceStore)
    lifecycle_manager: LifecycleManager = field(default_factory=LifecycleManager)

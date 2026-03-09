from engine.interfaces.discord.commands.analysis import AnalysisCommandPlugin
from engine.interfaces.discord.commands.orders import OrderCommandPlugin
from engine.interfaces.discord.commands.pattern import PatternCommandPlugin
from engine.interfaces.discord.commands.runtime import RuntimeCommandPlugin
from engine.interfaces.discord.commands.scanner import ScannerCommandPlugin

DEFAULT_COMMAND_PLUGINS = [
    RuntimeCommandPlugin(),
    OrderCommandPlugin(),
    AnalysisCommandPlugin(),
    PatternCommandPlugin(),
    ScannerCommandPlugin(),
]

__all__ = [
    "AnalysisCommandPlugin",
    "DEFAULT_COMMAND_PLUGINS",
    "OrderCommandPlugin",
    "PatternCommandPlugin",
    "RuntimeCommandPlugin",
    "ScannerCommandPlugin",
]

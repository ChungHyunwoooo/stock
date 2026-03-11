from engine.interfaces.discord.commands.analysis import AnalysisCommandPlugin
from engine.interfaces.discord.commands.backtest_history import BacktestHistoryPlugin
from engine.interfaces.discord.commands.lifecycle import LifecycleCommandPlugin
from engine.interfaces.discord.commands.orders import OrderCommandPlugin
from engine.interfaces.discord.commands.paper_trading import PaperTradingPlugin
from engine.interfaces.discord.commands.pattern import PatternCommandPlugin
from engine.interfaces.discord.commands.runtime import RuntimeCommandPlugin
from engine.interfaces.discord.commands.scanner import ScannerCommandPlugin
from engine.interfaces.discord.commands.status import StatusCommandPlugin

DEFAULT_COMMAND_PLUGINS = [
    StatusCommandPlugin(),
    RuntimeCommandPlugin(),
    OrderCommandPlugin(),
    AnalysisCommandPlugin(),
    PatternCommandPlugin(),
    ScannerCommandPlugin(),
    LifecycleCommandPlugin(),
    BacktestHistoryPlugin(),
    PaperTradingPlugin(),
]

__all__ = [
    "AnalysisCommandPlugin",
    "BacktestHistoryPlugin",
    "DEFAULT_COMMAND_PLUGINS",
    "LifecycleCommandPlugin",
    "OrderCommandPlugin",
    "PaperTradingPlugin",
    "PatternCommandPlugin",
    "RuntimeCommandPlugin",
    "ScannerCommandPlugin",
    "StatusCommandPlugin",
]


from __future__ import annotations

from pathlib import Path

from engine.application.trading.orchestrator import TradingOrchestrator
from engine.application.trading.strategies import DefinitionSignalGenerator
from engine.data.provider_base import get_provider
from engine.core.models import TradingSignal
from engine.strategy.plugin_runtime import strategy_source_plugins
from engine.schema import StrategyDefinition

class StrategyMonitorService:
    def __init__(
        self,
        orchestrator: TradingOrchestrator,
        signal_generator: DefinitionSignalGenerator | None = None,
        strategy_source_plugin: str = "json_definition",
    ) -> None:
        self.orchestrator = orchestrator
        self.signal_generator = signal_generator or DefinitionSignalGenerator()
        self.strategy_source = strategy_source_plugins.create(strategy_source_plugin)

    def load_strategy(self, path: str | Path) -> StrategyDefinition:
        return self.strategy_source.load(path)

    def evaluate_strategy(
        self,
        strategy: StrategyDefinition,
        symbol: str,
        start: str,
        end: str,
        timeframe: str | None = None,
        exchange: str = "binance",
        quantity: float = 1.0,
        execute: bool = True,
    ) -> TradingSignal | None:
        provider = get_provider(strategy.markets[0], exchange=exchange)
        frame = provider.fetch_ohlcv(symbol, start, end, timeframe or strategy.timeframes[0])
        signal = self.signal_generator.generate(strategy, frame, symbol)
        if signal is None:
            return None
        if execute:
            if "ohlcv_df" not in signal.metadata:
                signal.metadata["ohlcv_df"] = frame
            self.orchestrator.process_signal(signal)
        return signal

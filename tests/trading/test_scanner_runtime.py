
from engine.application.trading import AlertRuntimeConfig, AlertScannerRuntime
from engine.core import SignalAction, TradeSide, TradingSignal
from engine.execution import PaperBroker
from engine.notifications import MemoryNotifier
from engine.core import JsonRuntimeStore
from engine.application.trading.orchestrator import TradingOrchestrator
from engine.application.trading.signal_scanner import CooldownStore

class StubAnalysisService:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_recent(self, symbol: str, timeframe: str, lookback_bars: int = 300):
        self.calls += 1
        return [
            TradingSignal(
                strategy_id="test:1.0",
                symbol=symbol,
                timeframe=timeframe,
                action=SignalAction.entry,
                side=TradeSide.long,
                entry_price=100.0,
            )
        ]

def test_scanner_runtime_emits_and_then_respects_cooldown(tmp_path):
    store = JsonRuntimeStore(tmp_path / "runtime.json")
    notifier = MemoryNotifier()
    broker = PaperBroker()
    orchestrator = TradingOrchestrator(store, notifier, broker)
    analysis = StubAnalysisService()
    scanner = AlertScannerRuntime(
        orchestrator=orchestrator,
        config=AlertRuntimeConfig(
            enabled=True,
            symbols=["BTC/USDT"],
            timeframes=["5m"],
            cooldown_sec=3600,
            quantity=1.0,
        ),
        cooldown_store=CooldownStore(tmp_path / "scan-state.json"),
        analysis_service=analysis,
    )

    first = scanner.scan_once()
    second = scanner.scan_once()

    assert len(first) == 1
    assert len(second) == 0
    assert analysis.calls == 2
    assert len(notifier.signals) == 1

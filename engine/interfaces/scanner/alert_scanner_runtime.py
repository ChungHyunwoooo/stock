
from __future__ import annotations

from pathlib import Path

from engine.application.trading.signal_scanner import AlertRuntimeConfig, AlertScannerRuntime
from engine.interfaces.bootstrap import TradingRuntime, TradingRuntimeConfig, build_trading_runtime

_scanner: AlertScannerRuntime | None = None

def build_alert_scanner(
    runtime: TradingRuntime | None = None,
    config_path: str | Path = "config/alert_runtime.json",
) -> AlertScannerRuntime:
    trading_runtime = runtime or build_trading_runtime(TradingRuntimeConfig())
    config = AlertRuntimeConfig.load(config_path)
    return AlertScannerRuntime(orchestrator=trading_runtime.orchestrator, config=config)

def run_alert_scanner_background(config_path: str | Path = "config/alert_runtime.json") -> bool:
    global _scanner
    if _scanner is not None:
        return True
    scanner = build_alert_scanner(config_path=config_path)
    if not scanner.start_background():
        return False
    _scanner = scanner
    return True

def stop_alert_scanner() -> bool:
    global _scanner
    if _scanner is None:
        return True
    _scanner.stop()
    _scanner = None
    return True

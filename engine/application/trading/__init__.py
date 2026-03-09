from __future__ import annotations

from importlib import import_module

__all__ = [
    "AlertRuntimeConfig",
    "AlertScannerRuntime",
    "DefinitionSignalGenerator",
    "PendingOrderNotFoundError",
    "RecentSignalAnalysisService",
    "StrategyCatalog",
    "StrategyMonitorService",
    "TradingControlService",
    "TradingOrchestrator",
    "build_signal_presentation",
]

_MODULE_MAP = {
    "AlertRuntimeConfig": "engine.application.trading.scanner",
    "AlertScannerRuntime": "engine.application.trading.scanner",
    "DefinitionSignalGenerator": "engine.application.trading.strategies",
    "PendingOrderNotFoundError": "engine.application.trading.exceptions",
    "RecentSignalAnalysisService": "engine.application.trading.scanner",
    "StrategyCatalog": "engine.application.trading.strategies",
    "StrategyMonitorService": "engine.application.trading.monitor",
    "TradingControlService": "engine.application.trading.control",
    "TradingOrchestrator": "engine.application.trading.orchestrator",
    "build_signal_presentation": "engine.application.trading.presenters",
}


def __getattr__(name: str):
    try:
        module_name = _MODULE_MAP[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = import_module(module_name)
    return getattr(module, name)

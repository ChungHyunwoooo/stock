"""Detector registry for configurable signal strategy enablement.

Detector functions are resolved from `engine.strategy.upbit_scanner` and
ordered/enabled by config file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from engine.config_path import config_file

CONFIG_PATH = config_file("detectors.json")


@dataclass
class DetectorSpec:
    name: str
    fn_name: str
    enabled: bool = True
    priority: int = 100


DEFAULT_SPECS = [
    DetectorSpec("EMA_RSI_VWAP", "scan_ema_rsi_vwap", True, 10),
    DetectorSpec("SUPERTREND", "scan_supertrend", True, 20),
    DetectorSpec("MACD_DIV", "scan_macd_divergence", True, 30),
    DetectorSpec("STOCH_RSI", "scan_stoch_rsi", True, 40),
    DetectorSpec("FIBONACCI", "scan_fibonacci", True, 50),
    DetectorSpec("ICHIMOKU", "scan_ichimoku", True, 60),
    DetectorSpec("EARLY_PUMP", "scan_early_pump", True, 70),
    DetectorSpec("SMC", "scan_smc", True, 80),
    DetectorSpec("HIDDEN_DIV", "scan_hidden_divergence", True, 90),
    DetectorSpec("BB_RSI_STOCH", "scan_bb_rsi_stoch", True, 100),
    DetectorSpec("MEGA_PUMP", "scan_mega_pump_precursor", True, 110),
    DetectorSpec("TOMMY_MACD", "scan_tommy_macd", True, 120),
    DetectorSpec("TOMMY_BB_RSI", "scan_tommy_bb_rsi", True, 130),
]


def _save_defaults() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"detectors": [asdict(s) for s in DEFAULT_SPECS]}, indent=2, ensure_ascii=False)
    )


def load_specs() -> list[DetectorSpec]:
    if not CONFIG_PATH.exists():
        _save_defaults()
    try:
        data = json.loads(CONFIG_PATH.read_text())
        items = data.get("detectors", [])
        specs = []
        for item in items:
            specs.append(
                DetectorSpec(
                    name=item.get("name", ""),
                    fn_name=item.get("fn_name", ""),
                    enabled=bool(item.get("enabled", True)),
                    priority=int(item.get("priority", 100)),
                )
            )
        specs.sort(key=lambda x: x.priority)
        return specs
    except Exception as e:
        logger.warning("Failed to load detector specs: %s", e)
        return list(DEFAULT_SPECS)


def save_specs(specs: list[DetectorSpec]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"detectors": [asdict(s) for s in specs]}, indent=2, ensure_ascii=False)
    )


def resolve_detectors() -> list:
    import engine.strategy.upbit_scanner as scanner
    import engine.strategy.mega_pump as mega_pump
    import engine.strategy.tommy_macd as tommy_macd
    import engine.strategy.tommy_bb_rsi as tommy_bb_rsi

    _modules = [scanner, mega_pump, tommy_macd, tommy_bb_rsi]

    resolved = []
    for spec in load_specs():
        if not spec.enabled:
            continue
        fn = None
        for mod in _modules:
            fn = getattr(mod, spec.fn_name, None)
            if callable(fn):
                break
        if callable(fn):
            resolved.append(fn)
        else:
            logger.warning("Detector function not found: %s", spec.fn_name)
    return resolved


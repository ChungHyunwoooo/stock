"""Bot configuration system with persistent storage."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

from engine.config_path import config_file

CONFIG_PATH = config_file("bot_config.json")

# Default watch symbols (same as scanner)
DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT",
    "ADA/USDT", "DOT/USDT", "MATIC/USDT", "ARB/USDT",
    "OP/USDT", "SUI/USDT", "APT/USDT",
]


@dataclass
class BotConfig:
    # Scan settings
    scan_interval_sec: int = 300      # 5 minutes
    position_check_sec: int = 60      # 1 minute
    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))

    # Alert type toggles
    enable_momentum: bool = True      # S3
    enable_funding: bool = True       # S4
    enable_volume_spike: bool = True  # S6
    enable_rsi_extreme: bool = True   # S7
    enable_ema_cross: bool = True     # S8
    enable_bb_squeeze: bool = True    # S9
    enable_key_level: bool = True     # S10
    enable_candle_surge: bool = True  # S11
    enable_daily: bool = False        # S1/S2 (default off)

    # Position management
    trailing_stop_pct: float = 0.015  # 1.5%
    auto_position_track: bool = True

    # Alert filters
    min_confidence: float = 0.5
    cooldown_sec: int = 600           # 10 min cooldown per symbol+strategy

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> BotConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return cls.from_dict(data)
            except Exception as e:
                logger.warning("Failed to load bot config: %s", e)
        return cls()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> BotConfig:
        # Only use known fields, ignore unknown ones
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

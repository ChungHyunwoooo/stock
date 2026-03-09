"""Shadow scanner for safe migration (v2 dry-run alongside production scanner).

Runs lightweight scans without sending production alerts and compares
candidate signals against recent production alerts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from engine.analysis import build_context
from engine.strategy.detector_registry import resolve_detectors
from engine.strategy.exchange_adapters import get_exchange_adapter
from engine.strategy import upbit_scanner as scanner

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "upbit_shadow.json"

_running = False
_task: asyncio.Task | None = None
_config = None
_reports: list[dict] = []
_last_run_at = ""
_scan_count = 0


@dataclass
class UpbitShadowConfig:
    enabled: bool = False
    scan_interval_sec: int = 120
    max_symbols: int = 25
    symbols: list[str] = field(default_factory=list)
    interval: str = "5m"
    bar_count: int = 200
    min_volume_krw: float = 10_000_000_000
    sample_size: int = 10
    compare_window_sec: int = 600
    exchange: str = "upbit"

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> UpbitShadowConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                known = {f.name for f in cls.__dataclass_fields__.values()}
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception as e:
                logger.warning("Failed to load shadow config: %s", e)
        return cls()


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _signal_key(sig) -> str:
    return f"{sig.symbol}|{sig.strategy}|{sig.side}|{sig.timeframe}"


def _parse_utc(ts: str) -> float:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _select_symbols(cfg: UpbitShadowConfig) -> list[str]:
    adapter = get_exchange_adapter(cfg.exchange)
    auto = adapter.get_active_symbols(max_symbols=max(1, cfg.max_symbols))
    merged = list(auto)
    seen = set(auto)
    for s in cfg.symbols:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    return merged[: max(1, cfg.max_symbols)]


def _run_once(cfg: UpbitShadowConfig) -> dict:
    prod_cfg = scanner.UpbitScannerConfig.load()
    strategies = resolve_detectors()
    symbols = _select_symbols(cfg)
    adapter = get_exchange_adapter(cfg.exchange)

    shadow_keys: set[str] = set()
    errors = 0

    for symbol in symbols:
        try:
            df = adapter.fetch_ohlcv(symbol, interval=cfg.interval, count=cfg.bar_count)
            if df is None:
                continue
            try:
                ctx = build_context(df)
            except Exception:
                ctx = {}

            for scan_fn in strategies:
                try:
                    sig = scan_fn(df, symbol, prod_cfg, context=ctx)
                except TypeError:
                    try:
                        sig = scan_fn(df, symbol, prod_cfg)
                    except Exception:
                        continue
                except Exception:
                    continue
                if sig is None:
                    continue
                sig.timeframe = "5m"
                sig = scanner.validate_signal_rr(sig)
                if sig is None:
                    continue
                shadow_keys.add(_signal_key(sig))
        except Exception:
            errors += 1

    # Compare to recent production alerts
    now_ts = time.time()
    prod_hist = scanner.get_alert_history()
    prod_recent = []
    for item in prod_hist:
        ts = _parse_utc(item.get("timestamp", ""))
        if ts > 0 and (now_ts - ts) <= cfg.compare_window_sec:
            prod_recent.append(
                f"{item.get('symbol')}|{item.get('strategy')}|{item.get('side')}|{item.get('timeframe')}"
            )
    prod_keys = set(prod_recent)

    overlap = shadow_keys & prod_keys
    shadow_only = shadow_keys - prod_keys
    prod_only = prod_keys - shadow_keys

    report = {
        "timestamp": _utc_now_str(),
        "exchange": cfg.exchange,
        "symbols": len(symbols),
        "shadow_signals": len(shadow_keys),
        "prod_recent_signals": len(prod_keys),
        "overlap": len(overlap),
        "shadow_only": len(shadow_only),
        "prod_only": len(prod_only),
        "errors": errors,
        "sample_shadow_only": sorted(list(shadow_only))[: cfg.sample_size],
        "sample_prod_only": sorted(list(prod_only))[: cfg.sample_size],
    }
    return report


async def _loop() -> None:
    global _scan_count, _last_run_at
    while _running:
        try:
            report = await asyncio.get_event_loop().run_in_executor(None, lambda: _run_once(_config))
            _scan_count += 1
            _last_run_at = report["timestamp"]
            _reports.insert(0, report)
            if len(_reports) > 100:
                _reports.pop()
            logger.info(
                "Shadow scan #%d: shadow=%d prod=%d overlap=%d err=%d",
                _scan_count,
                report["shadow_signals"],
                report["prod_recent_signals"],
                report["overlap"],
                report["errors"],
            )
        except Exception as e:
            logger.error("Shadow loop error: %s", e)

        await asyncio.sleep(max(15, _config.scan_interval_sec))


def start() -> bool:
    global _running, _task, _config
    if _running:
        return False
    _config = UpbitShadowConfig.load()
    _running = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop())
    logger.info("Upbit shadow scanner started (interval=%ds)", _config.scan_interval_sec)
    return True


def stop() -> bool:
    global _running, _task
    if not _running:
        return False
    _running = False
    if _task:
        _task.cancel()
        _task = None
    logger.info("Upbit shadow scanner stopped")
    return True


def status() -> dict:
    return {
        "running": _running,
        "scan_interval_sec": _config.scan_interval_sec if _config else 120,
        "scan_count": _scan_count,
        "last_run_at": _last_run_at,
        "recent_reports": len(_reports),
    }


def get_config() -> UpbitShadowConfig:
    return _config or UpbitShadowConfig.load()


def update_config(data: dict) -> UpbitShadowConfig:
    global _config
    if _config is None:
        _config = UpbitShadowConfig.load()
    for k, v in data.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
    _config.save()
    return _config


def get_reports() -> list[dict]:
    return list(_reports)

"""Background scheduler for automated signal scanning."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from engine.alerts.bot_config import BotConfig
from engine.alerts.positions import PositionTracker
from engine.alerts.discord import send_signal

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_running = False

# Scan intervals in seconds
SCALPING_INTERVAL = 5 * 60   # 5 minutes
DAILY_INTERVAL = 60 * 60     # 1 hour (daily strategies don't change fast)

_config: BotConfig | None = None
_tracker: PositionTracker | None = None
_cooldowns: dict[str, float] = {}   # "symbol:strategy" -> timestamp
_last_scan: float = 0
_last_position_check: float = 0
_alert_history: list[dict] = []     # max 100 recent alerts
_start_time: float = 0


def _in_cooldown(sig) -> bool:
    key = f"{sig.symbol}:{sig.strategy}"
    last = _cooldowns.get(key, 0)
    return (time.time() - last) < _config.cooldown_sec


def _record_cooldown(sig) -> None:
    key = f"{sig.symbol}:{sig.strategy}"
    _cooldowns[key] = time.time()


def _add_alert_history(alert_type: str, obj) -> None:
    from datetime import datetime, timezone
    entry = {
        "type": alert_type,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    if alert_type == "signal":
        entry.update({"symbol": obj.symbol, "strategy": obj.strategy, "side": obj.side, "entry": obj.entry, "confidence": obj.confidence, "message": obj.reason})
    else:  # position alert
        entry.update({"symbol": obj.position.signal.symbol, "strategy": obj.position.signal.strategy, "alert_type": obj.type, "message": obj.message, "pnl_pct": obj.position.pnl_pct})
    _alert_history.insert(0, entry)
    if len(_alert_history) > 100:
        _alert_history.pop()


def _fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch latest prices using ccxt."""
    import ccxt
    try:
        ex = ccxt.binance({"options": {"defaultType": "future"}})
        tickers = ex.fetch_tickers(symbols)
        return {sym: float(t["last"]) for sym, t in tickers.items() if t.get("last")}
    except Exception as e:
        logger.warning("Price fetch error: %s", e)
        return {}


def _send_position_alert(alert) -> None:
    """Send position alert to Discord."""
    try:
        from engine.alerts.discord import send_position_alert
        send_position_alert(alert)
    except Exception as e:
        logger.warning("Position alert send error: %s", e)


async def _bot_loop() -> None:
    global _last_scan, _last_position_check
    while _running:
        try:
            now = time.time()

            # 1) Signal scan
            if now - _last_scan >= _config.scan_interval_sec:
                from engine.strategy.scanner import run_scan
                from engine.regime.crypto import CryptoRegimeEngine

                regime = "SELECTIVE"
                try:
                    regime = CryptoRegimeEngine().compute().regime
                except Exception:
                    pass

                run_daily = (now - _last_scan) >= DAILY_INTERVAL

                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: run_scan(
                        regime=regime,
                        symbols=_config.symbols,
                        notify=True,
                        scan_scalping=True,
                        scan_daily=run_daily and _config.enable_daily,
                        scan_daytrading=True,
                    ),
                )

                for sig in result.signals:
                    if sig.confidence >= _config.min_confidence and not _in_cooldown(sig):
                        _record_cooldown(sig)
                        _add_alert_history("signal", sig)
                        if _config.auto_position_track:
                            _tracker.open_position(sig, _config.trailing_stop_pct)

                _last_scan = now
                logger.info("Bot scan: %d signals, %d errors", len(result.signals), len(result.errors))

            # 2) Position monitoring
            if _tracker and now - _last_position_check >= _config.position_check_sec:
                open_syms = _tracker.open_symbols()
                if open_syms:
                    prices = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: _fetch_current_prices(open_syms)
                    )
                    alerts = _tracker.update_prices(prices)
                    for alert in alerts:
                        _send_position_alert(alert)
                        _add_alert_history("position", alert)
                _last_position_check = now

        except Exception as e:
            logger.error("Bot loop error: %s", e)

        await asyncio.sleep(30)


def start() -> bool:
    global _task, _running, _config, _tracker, _start_time
    if _running:
        return False
    _config = BotConfig.load()
    _tracker = PositionTracker()
    _running = True
    _start_time = time.time()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    _task = loop.create_task(_bot_loop())
    logger.info("Bot started (scan every %ds, position check every %ds)", _config.scan_interval_sec, _config.position_check_sec)
    return True


def stop() -> bool:
    global _task, _running
    if not _running:
        return False
    _running = False
    if _task:
        _task.cancel()
        _task = None
    if _tracker:
        _tracker.save()
    logger.info("Bot stopped")
    return True


def is_running() -> bool:
    return _running


def status() -> dict:
    return {
        "running": _running,
        "scalping_interval_sec": SCALPING_INTERVAL,
        "daily_interval_sec": DAILY_INTERVAL,
        "scan_interval_sec": _config.scan_interval_sec if _config else 300,
        "position_check_sec": _config.position_check_sec if _config else 60,
        "open_positions": len(_tracker.get_open_positions()) if _tracker else 0,
        "uptime_sec": int(time.time() - _start_time) if _running else 0,
    }


def get_config() -> BotConfig | None:
    return _config


def get_tracker() -> PositionTracker | None:
    return _tracker


def get_alert_history() -> list[dict]:
    return list(_alert_history)


def update_config(data: dict) -> BotConfig:
    global _config
    if _config is None:
        _config = BotConfig.load()
    for k, v in data.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
    _config.save()
    return _config

"""Bot control and position management endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from api.routers.alerts import SignalOut

router = APIRouter(prefix="/bot", tags=["bot"])

# --- Pydantic Models ---

class PositionOut(BaseModel):
    id: str
    signal: SignalOut
    status: str
    entry_price: float
    current_price: float
    stop_loss: float
    take_profits: list[float]
    trailing_stop: float | None
    trailing_pct: float
    highest_since_entry: float
    lowest_since_entry: float
    pnl_pct: float
    opened_at: str
    closed_at: str | None
    tp1_hit: bool
    tp2_hit: bool

class BotConfigOut(BaseModel):
    scan_interval_sec: int
    position_check_sec: int
    symbols: list[str]
    enable_momentum: bool
    enable_funding: bool
    enable_volume_spike: bool
    enable_rsi_extreme: bool
    enable_ema_cross: bool
    enable_bb_squeeze: bool
    enable_key_level: bool
    enable_candle_surge: bool
    enable_daily: bool
    trailing_stop_pct: float
    auto_position_track: bool
    min_confidence: float
    cooldown_sec: int

class BotConfigUpdate(BaseModel):
    scan_interval_sec: int | None = None
    position_check_sec: int | None = None
    symbols: list[str] | None = None
    enable_momentum: bool | None = None
    enable_funding: bool | None = None
    enable_volume_spike: bool | None = None
    enable_rsi_extreme: bool | None = None
    enable_ema_cross: bool | None = None
    enable_bb_squeeze: bool | None = None
    enable_key_level: bool | None = None
    enable_candle_surge: bool | None = None
    enable_daily: bool | None = None
    trailing_stop_pct: float | None = None
    auto_position_track: bool | None = None
    min_confidence: float | None = None
    cooldown_sec: int | None = None

class BotStatusOut(BaseModel):
    running: bool
    scan_interval_sec: int
    position_check_sec: int
    open_positions: int
    uptime_sec: int

class AlertHistoryItem(BaseModel):
    type: str
    timestamp: str
    symbol: str | None = None
    strategy: str | None = None
    side: str | None = None
    entry: float | None = None
    confidence: float | None = None
    message: str | None = None
    alert_type: str | None = None
    pnl_pct: float | None = None

# --- Helper to convert Position to PositionOut ---

def _pos_to_out(pos) -> PositionOut:
    sig = pos.signal
    return PositionOut(
        id=pos.id,
        signal=SignalOut(
            strategy=sig.strategy, symbol=sig.symbol, side=sig.side,
            entry=sig.entry, stop_loss=sig.stop_loss,
            take_profits=sig.take_profits, leverage=sig.leverage,
            timeframe=sig.timeframe, confidence=sig.confidence,
            reason=sig.reason, timestamp=sig.timestamp,
        ),
        status=pos.status,
        entry_price=pos.entry_price,
        current_price=pos.current_price,
        stop_loss=pos.stop_loss,
        take_profits=pos.take_profits,
        trailing_stop=pos.trailing_stop,
        trailing_pct=pos.trailing_pct,
        highest_since_entry=pos.highest_since_entry,
        lowest_since_entry=pos.lowest_since_entry,
        pnl_pct=pos.pnl_pct,
        opened_at=pos.opened_at,
        closed_at=pos.closed_at,
        tp1_hit=pos.tp1_hit,
        tp2_hit=pos.tp2_hit,
    )

# --- Endpoints ---

@router.get("/status", response_model=BotStatusOut)
def bot_status():
    from engine.strategy.scheduler import status
    s = status()
    return BotStatusOut(**s)

@router.post("/start", response_model=BotStatusOut)
def bot_start():
    from engine.strategy.scheduler import start, status
    start()
    return BotStatusOut(**status())

@router.post("/stop", response_model=BotStatusOut)
def bot_stop():
    from engine.strategy.scheduler import stop, status
    stop()
    return BotStatusOut(**status())

@router.get("/config", response_model=BotConfigOut)
def bot_config():
    from engine.strategy.scheduler import get_config
    from engine.notifications.alert_bot_config import BotConfig
    cfg = get_config() or BotConfig.load()
    return BotConfigOut(**cfg.to_dict())

@router.put("/config", response_model=BotConfigOut)
def bot_update_config(update: BotConfigUpdate):
    from engine.strategy.scheduler import update_config
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg = update_config(data)
    return BotConfigOut(**cfg.to_dict())

@router.get("/positions", response_model=list[PositionOut])
def bot_positions():
    from engine.strategy.scheduler import get_tracker
    from engine.notifications.alert_positions import PositionTracker
    tracker = get_tracker() or PositionTracker()
    return [_pos_to_out(p) for p in tracker.get_open_positions()]

@router.get("/positions/history", response_model=list[PositionOut])
def bot_positions_history():
    from engine.strategy.scheduler import get_tracker
    from engine.notifications.alert_positions import PositionTracker
    tracker = get_tracker() or PositionTracker()
    return [_pos_to_out(p) for p in tracker.get_history()]

@router.post("/positions/{pos_id}/close")
def bot_close_position(pos_id: str):
    from engine.strategy.scheduler import get_tracker
    tracker = get_tracker()
    if not tracker:
        return {"error": "Bot not running"}
    alert = tracker.close_position(pos_id, "MANUAL")
    if alert is None:
        return {"error": "Position not found"}
    return {"success": True, "message": alert.message}

@router.get("/alerts/history", response_model=list[AlertHistoryItem])
def bot_alert_history():
    from engine.strategy.scheduler import get_alert_history
    history = get_alert_history()
    return [AlertHistoryItem(**h) for h in history]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.get("/analysis/exchange-dominance")
def exchange_dominance_analysis(
    base: str = "BTC",
    usdkrw: float = 1350.0,
    fee_buffer_bps: float = 20.0,
):
    from engine.analysis.exchange_dominance import analyze_exchange_dominance

    return analyze_exchange_dominance(
        base=base,
        usdkrw=usdkrw,
        fee_buffer_bps=fee_buffer_bps,
    )

# ---------------------------------------------------------------------------
# Discord Bot
# ---------------------------------------------------------------------------

@router.post("/discord-bot/start")
def discord_bot_start():
    """Start the interactive Discord bot."""
    from engine.interfaces.discord import run_bot_background
    ok = run_bot_background()
    return {"success": ok, "message": "Discord bot started" if ok else "Failed to start"}

@router.post("/discord-bot/stop")
def discord_bot_stop():
    """Stop the interactive Discord bot."""
    from engine.interfaces.discord import stop_bot
    ok = stop_bot()
    return {"success": ok}

@router.get("/discord-bot/status")
def discord_bot_status():
    """Check Discord bot connection state."""
    from engine.interfaces.discord.control_bot import _bot, _bot_running
    if _bot is None:
        return {"running": False, "connected": False, "user": None}
    return {
        "running": _bot_running,
        "connected": _bot.is_ready() if hasattr(_bot, "is_ready") else False,
        "user": str(_bot.user) if _bot.user else None,
    }

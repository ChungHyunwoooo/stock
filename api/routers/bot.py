"""Bot control and position management endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

router = APIRouter(prefix="/bot", tags=["bot"])


# --- Pydantic Models ---

class SignalOut(BaseModel):
    strategy: str
    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profits: list[float]
    leverage: int
    timeframe: str
    confidence: float
    reason: str
    timestamp: str


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
    from engine.alerts.bot_config import BotConfig
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
    from engine.alerts.positions import PositionTracker
    tracker = get_tracker() or PositionTracker()
    return [_pos_to_out(p) for p in tracker.get_open_positions()]


@router.get("/positions/history", response_model=list[PositionOut])
def bot_positions_history():
    from engine.strategy.scheduler import get_tracker
    from engine.alerts.positions import PositionTracker
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
# Upbit KRW Scanner
# ---------------------------------------------------------------------------

class UpbitScannerStatus(BaseModel):
    running: bool
    scan_interval_sec: int
    symbols_count: int
    scan_count: int
    last_scan: str
    recent_alerts: int
    mode: str = "polling"
    ws_status: dict | None = None
    cache_stats: dict | None = None
    enable_mtf: bool = False
    timeframes: dict | None = None


class UpbitConfigOut(BaseModel):
    enabled: bool = True
    scan_interval_sec: int = 30
    symbols: list[str] = []
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    vol_mult: float = 1.5
    sl_pct: float = 0.01
    tp1_pct: float = 0.01
    tp2_pct: float = 0.02
    tp3_pct: float = 0.03
    enable_ema_rsi_vwap: bool = True
    enable_supertrend: bool = True
    enable_macd_div: bool = True
    enable_stoch_rsi: bool = True
    enable_fibonacci: bool = True
    enable_ichimoku: bool = True
    enable_early_pump: bool = True
    cooldown_sec: int = 600
    send_chart: bool = True
    enable_mtf: bool = True
    ws_enabled: bool = True
    parallel_fetch: bool = True
    enable_tf_4h: bool = True
    enable_tf_1h: bool = True
    enable_tf_30m: bool = True
    enable_tf_5m: bool = True


class UpbitConfigUpdate(BaseModel):
    enabled: bool | None = None
    scan_interval_sec: int | None = None
    symbols: list[str] | None = None
    ema_fast: int | None = None
    ema_slow: int | None = None
    vol_mult: float | None = None
    sl_pct: float | None = None
    tp1_pct: float | None = None
    tp2_pct: float | None = None
    tp3_pct: float | None = None
    enable_ema_rsi_vwap: bool | None = None
    enable_supertrend: bool | None = None
    enable_macd_div: bool | None = None
    enable_stoch_rsi: bool | None = None
    enable_fibonacci: bool | None = None
    enable_ichimoku: bool | None = None
    enable_early_pump: bool | None = None
    cooldown_sec: int | None = None
    send_chart: bool | None = None
    enable_mtf: bool | None = None
    ws_enabled: bool | None = None
    parallel_fetch: bool | None = None
    enable_tf_4h: bool | None = None
    enable_tf_1h: bool | None = None
    enable_tf_30m: bool | None = None
    enable_tf_5m: bool | None = None


@router.get("/upbit/status", response_model=UpbitScannerStatus)
def upbit_status():
    from engine.strategy.upbit_scanner import status
    return UpbitScannerStatus(**status())


@router.post("/upbit/start", response_model=UpbitScannerStatus)
def upbit_start():
    from engine.strategy.upbit_scanner import start, status
    start()
    return UpbitScannerStatus(**status())


@router.post("/upbit/stop", response_model=UpbitScannerStatus)
def upbit_stop():
    from engine.strategy.upbit_scanner import stop, status
    stop()
    return UpbitScannerStatus(**status())


@router.get("/upbit/config", response_model=UpbitConfigOut)
def upbit_config():
    from engine.strategy.upbit_scanner import get_config, UpbitScannerConfig
    cfg = get_config() or UpbitScannerConfig.load()
    from dataclasses import asdict
    return UpbitConfigOut(**asdict(cfg))


@router.put("/upbit/config", response_model=UpbitConfigOut)
def upbit_update_config(update: UpbitConfigUpdate):
    from engine.strategy.upbit_scanner import update_config
    from dataclasses import asdict
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg = update_config(data)
    return UpbitConfigOut(**asdict(cfg))


class UpbitShadowStatus(BaseModel):
    running: bool
    scan_interval_sec: int
    scan_count: int
    last_run_at: str
    recent_reports: int


class UpbitShadowConfigOut(BaseModel):
    enabled: bool = False
    scan_interval_sec: int = 120
    max_symbols: int = 25
    symbols: list[str] = []
    interval: str = "5m"
    bar_count: int = 200
    min_volume_krw: float = 10_000_000_000
    sample_size: int = 10
    compare_window_sec: int = 600
    exchange: str = "upbit"


class UpbitShadowConfigUpdate(BaseModel):
    enabled: bool | None = None
    scan_interval_sec: int | None = None
    max_symbols: int | None = None
    symbols: list[str] | None = None
    interval: str | None = None
    bar_count: int | None = None
    min_volume_krw: float | None = None
    sample_size: int | None = None
    compare_window_sec: int | None = None
    exchange: str | None = None


@router.get("/upbit/shadow/status", response_model=UpbitShadowStatus)
def upbit_shadow_status():
    from engine.strategy.upbit_shadow import status
    return UpbitShadowStatus(**status())


@router.post("/upbit/shadow/start", response_model=UpbitShadowStatus)
def upbit_shadow_start():
    from engine.strategy.upbit_shadow import start, status
    start()
    return UpbitShadowStatus(**status())


@router.post("/upbit/shadow/stop", response_model=UpbitShadowStatus)
def upbit_shadow_stop():
    from engine.strategy.upbit_shadow import stop, status
    stop()
    return UpbitShadowStatus(**status())


@router.get("/upbit/shadow/config", response_model=UpbitShadowConfigOut)
def upbit_shadow_config():
    from engine.strategy.upbit_shadow import get_config
    from dataclasses import asdict
    cfg = get_config()
    return UpbitShadowConfigOut(**asdict(cfg))


@router.put("/upbit/shadow/config", response_model=UpbitShadowConfigOut)
def upbit_shadow_update_config(update: UpbitShadowConfigUpdate):
    from engine.strategy.upbit_shadow import update_config
    from dataclasses import asdict
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg = update_config(data)
    return UpbitShadowConfigOut(**asdict(cfg))


@router.get("/upbit/shadow/reports")
def upbit_shadow_reports(limit: int = 20):
    from engine.strategy.upbit_shadow import get_reports
    items = get_reports()
    return {"reports": items[: max(1, min(limit, 100))]}


class AlertV2Status(BaseModel):
    running: bool
    mode: str
    exchange: str
    scan_interval_sec: int
    scan_count: int
    last_scan_at: str
    recent_reports: int


class AlertV2ConfigOut(BaseModel):
    enabled: bool = False
    mode: str = "shadow"
    exchange: str = "upbit"
    scan_interval_sec: int = 30
    interval: str = "5m"
    bar_count: int = 200
    max_symbols: int = 20
    symbols: list[str] = []
    compare_window_sec: int = 600
    rollout_pct: int = 20
    min_confidence: float = 0.5
    send_chart: bool = False
    usdkrw: float = 1350.0
    sample_size: int = 10
    track_pnl: bool = True
    close_after_sec: int = 3600
    enable_tf_5m: bool = True
    enable_tf_30m: bool = True
    enable_tf_1h: bool = True
    enable_tf_4h: bool = True
    enable_regime_filter: bool = True


class AlertV2ConfigUpdate(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    exchange: str | None = None
    scan_interval_sec: int | None = None
    interval: str | None = None
    bar_count: int | None = None
    max_symbols: int | None = None
    symbols: list[str] | None = None
    compare_window_sec: int | None = None
    rollout_pct: int | None = None
    min_confidence: float | None = None
    send_chart: bool | None = None
    usdkrw: float | None = None
    sample_size: int | None = None
    track_pnl: bool | None = None
    close_after_sec: int | None = None
    enable_tf_5m: bool | None = None
    enable_tf_30m: bool | None = None
    enable_tf_1h: bool | None = None
    enable_tf_4h: bool | None = None
    enable_regime_filter: bool | None = None


@router.get("/alert-v2/status", response_model=AlertV2Status)
def alert_v2_status():
    from engine.strategy.alert_v2 import status
    return AlertV2Status(**status())


@router.post("/alert-v2/start", response_model=AlertV2Status)
def alert_v2_start():
    from engine.strategy.alert_v2 import start, status
    start()
    return AlertV2Status(**status())


@router.post("/alert-v2/stop", response_model=AlertV2Status)
def alert_v2_stop():
    from engine.strategy.alert_v2 import stop, status
    stop()
    return AlertV2Status(**status())


@router.get("/alert-v2/config", response_model=AlertV2ConfigOut)
def alert_v2_config():
    from engine.strategy.alert_v2 import get_config
    from dataclasses import asdict
    cfg = get_config()
    return AlertV2ConfigOut(**asdict(cfg))


@router.put("/alert-v2/config", response_model=AlertV2ConfigOut)
def alert_v2_update_config(update: AlertV2ConfigUpdate):
    from engine.strategy.alert_v2 import update_config
    from dataclasses import asdict
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg = update_config(data)
    return AlertV2ConfigOut(**asdict(cfg))


@router.get("/alert-v2/reports")
def alert_v2_reports(limit: int = 20):
    from engine.strategy.alert_v2 import get_reports
    items = get_reports()
    return {"reports": items[: max(1, min(limit, 200))]}


@router.get("/alert-v2/performance")
def alert_v2_performance():
    from engine.strategy.alert_v2 import get_performance
    return get_performance()


@router.get("/detectors")
def detector_list():
    from engine.strategy.detector_registry import load_specs
    from dataclasses import asdict
    return {"detectors": [asdict(s) for s in load_specs()]}


@router.put("/detectors")
def detector_update(payload: dict):
    from engine.strategy.detector_registry import DetectorSpec, save_specs
    items = payload.get("detectors", [])
    specs = []
    for i in items:
        specs.append(
            DetectorSpec(
                name=i.get("name", ""),
                fn_name=i.get("fn_name", ""),
                enabled=bool(i.get("enabled", True)),
                priority=int(i.get("priority", 100)),
            )
        )
    save_specs(specs)
    return {"ok": True, "count": len(specs)}


@router.get("/analysis/cross-exchange")
def cross_exchange_analysis(
    symbol_upbit: str = "KRW-BTC",
    symbol_binance: str = "BTC/USDT",
    interval: str = "5m",
    bars: int = 300,
    usdkrw: float = 1350.0,
):
    from engine.analysis.cross_exchange import lead_lag_score, summarize_cross_exchange
    from engine.strategy.exchange_adapters import UpbitAdapter, BinanceAdapter

    up = UpbitAdapter()
    bn = BinanceAdapter()
    df_up = up.fetch_ohlcv(symbol_upbit, interval=interval, count=bars)
    df_bn = bn.fetch_ohlcv(symbol_binance, interval=interval, count=bars)
    if df_up is None or df_bn is None or df_up.empty or df_bn.empty:
        return {"error": "insufficient_data", "symbol_upbit": symbol_upbit, "symbol_binance": symbol_binance}

    s = lead_lag_score(df_bn["close"], df_up["close"], max_lag=5)
    c = summarize_cross_exchange(
        krw_price=float(df_up["close"].iloc[-1]),
        usdt_price=float(df_bn["close"].iloc[-1]),
        usdkrw=usdkrw,
        execution_price=float(df_up["close"].iloc[-1]),
        reference_price=float(df_bn["close"].iloc[-1]) * usdkrw,
    )
    return {
        "symbol_upbit": symbol_upbit,
        "symbol_binance": symbol_binance,
        "interval": interval,
        "bars": bars,
        "lead_lag": s,
        "cross_exchange": c,
    }


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


@router.get("/upbit/alerts")
def upbit_alerts():
    from engine.strategy.upbit_scanner import get_alert_history
    return get_alert_history()


@router.get("/upbit/mtf/{symbol}")
def upbit_mtf_analysis(symbol: str):
    """Get multi-timeframe trend analysis for a symbol."""
    from engine.strategy.upbit_scanner import analyze_symbol_mtf
    ticker = f"KRW-{symbol.upper()}"
    result = analyze_symbol_mtf(ticker)
    if result is None:
        return {"error": f"MTF analysis failed for {ticker}", "symbol": ticker}
    return {"symbol": ticker, **result}


@router.get("/upbit/cache/stats")
def upbit_cache_stats():
    """Get OHLCV cache statistics."""
    from engine.strategy.upbit_scanner import get_cache_manager
    mgr = get_cache_manager()
    if mgr is None:
        return {"active": False, "message": "Cache not initialized"}
    return {"active": True, **mgr.stats()}


@router.delete("/upbit/strategy")
def upbit_disable():
    """Disable the Upbit scanner strategy."""
    from engine.strategy.upbit_scanner import stop, update_config
    stop()
    update_config({"enabled": False})
    return {"success": True, "message": "Upbit EMA+RSI+VWAP 전략이 비활성화되었습니다."}


# ---------------------------------------------------------------------------
# Swing Scanner (1h swing trading)
# ---------------------------------------------------------------------------

class SwingScannerStatus(BaseModel):
    running: bool
    scan_interval_sec: int
    symbols_count: int
    scan_count: int
    last_scan: str
    recent_alerts: int
    mode: str = "polling"
    enable_mtf: bool = True
    discord_channel: str = "swing"


class SwingConfigOut(BaseModel):
    enabled: bool = True
    scan_interval_sec: int = 3600
    symbols: list[str] = []
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    supertrend_period: int = 14
    supertrend_multiplier: float = 3.5
    adx_period: int = 14
    atr_period: int = 14
    sl_atr_mult: float = 2.0
    tp1_atr_mult: float = 3.0
    tp2_atr_mult: float = 5.0
    tp3_atr_mult: float = 8.0
    sl_mode: str = "hybrid"
    tp_mode: str = "staged"
    enable_ema_cross: bool = True
    enable_ichimoku: bool = True
    enable_supertrend: bool = True
    enable_macd_div: bool = True
    enable_smc: bool = True
    enable_bb_squeeze: bool = True
    cooldown_sec: int = 3600
    discord_channel: str = "swing"
    enable_mtf: bool = True
    send_chart: bool = True
    leverage: int = 1
    parallel_fetch: bool = True


class SwingConfigUpdate(BaseModel):
    enabled: bool | None = None
    scan_interval_sec: int | None = None
    symbols: list[str] | None = None
    ema_fast: int | None = None
    ema_slow: int | None = None
    supertrend_period: int | None = None
    supertrend_multiplier: float | None = None
    sl_atr_mult: float | None = None
    tp1_atr_mult: float | None = None
    tp2_atr_mult: float | None = None
    tp3_atr_mult: float | None = None
    sl_mode: str | None = None
    tp_mode: str | None = None
    enable_ema_cross: bool | None = None
    enable_ichimoku: bool | None = None
    enable_supertrend: bool | None = None
    enable_macd_div: bool | None = None
    enable_smc: bool | None = None
    enable_bb_squeeze: bool | None = None
    cooldown_sec: int | None = None
    discord_channel: str | None = None
    enable_mtf: bool | None = None
    send_chart: bool | None = None
    parallel_fetch: bool | None = None


@router.get("/swing/status", response_model=SwingScannerStatus)
def swing_status():
    from engine.strategy.swing_scanner import status
    return SwingScannerStatus(**status())


@router.post("/swing/start", response_model=SwingScannerStatus)
def swing_start():
    from engine.strategy.swing_scanner import start, status
    start()
    return SwingScannerStatus(**status())


@router.post("/swing/stop", response_model=SwingScannerStatus)
def swing_stop():
    from engine.strategy.swing_scanner import stop, status
    stop()
    return SwingScannerStatus(**status())


@router.get("/swing/config", response_model=SwingConfigOut)
def swing_config():
    from engine.strategy.swing_scanner import get_config, SwingScannerConfig
    cfg = get_config() or SwingScannerConfig.load()
    from dataclasses import asdict
    return SwingConfigOut(**asdict(cfg))


@router.put("/swing/config", response_model=SwingConfigOut)
def swing_update_config(update: SwingConfigUpdate):
    from engine.strategy.swing_scanner import update_config
    from dataclasses import asdict
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    cfg = update_config(data)
    return SwingConfigOut(**asdict(cfg))


@router.get("/swing/alerts")
def swing_alerts():
    from engine.strategy.swing_scanner import get_alert_history
    return get_alert_history()


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

"""Alert configuration and signal scanner endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Query

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Discord webhook config
# ---------------------------------------------------------------------------

class WebhookConfig(BaseModel):
    webhook_url: str


class WebhookStatus(BaseModel):
    configured: bool
    webhook_url: str | None = None


@router.get("/discord", response_model=WebhookStatus)
def get_discord_config() -> WebhookStatus:
    from engine.alerts.discord import load_webhook_url
    url = load_webhook_url()
    return WebhookStatus(
        configured=url is not None,
        webhook_url=url[:40] + "..." if url else None,
    )


@router.post("/discord", response_model=WebhookStatus)
def set_discord_config(config: WebhookConfig) -> WebhookStatus:
    from engine.alerts.discord import save_webhook_url
    save_webhook_url(config.webhook_url)
    return WebhookStatus(configured=True, webhook_url=config.webhook_url[:40] + "...")


@router.post("/discord/test")
def test_discord() -> dict:
    from engine.alerts.discord import send_text
    ok = send_text("\u2705 Trading Bot 알림 테스트 — Discord 연결 성공!")
    return {"success": ok}


# ---------------------------------------------------------------------------
# Signal scanner
# ---------------------------------------------------------------------------

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


class ScanResponse(BaseModel):
    signals: list[SignalOut]
    errors: list[str]
    scanned_at: str


@router.post("/scan", response_model=ScanResponse)
def run_scanner(
    symbols: list[str] | None = None,
    notify: bool = Query(True, description="Send Discord alerts"),
    scan_scalping: bool = Query(True, description="Run scalping strategies (5m)"),
    scan_daily: bool = Query(True, description="Run daily strategies (S1/S2)"),
) -> ScanResponse:
    """Run all strategies against watched symbols and return signals."""
    from engine.strategy.scanner import run_scan
    from engine.regime.crypto import CryptoRegimeEngine

    # Get current regime
    try:
        regime_state = CryptoRegimeEngine().compute()
        regime = regime_state.regime
    except Exception:
        regime = "SELECTIVE"

    result = run_scan(
        regime=regime,
        symbols=symbols,
        notify=notify,
        scan_scalping=scan_scalping,
        scan_daily=scan_daily,
    )

    return ScanResponse(
        signals=[
            SignalOut(
                strategy=s.strategy,
                symbol=s.symbol,
                side=s.side,
                entry=s.entry,
                stop_loss=s.stop_loss,
                take_profits=s.take_profits,
                leverage=s.leverage,
                timeframe=s.timeframe,
                confidence=s.confidence,
                reason=s.reason,
                timestamp=s.timestamp,
            )
            for s in result.signals
        ],
        errors=result.errors,
        scanned_at=result.scanned_at,
    )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class SchedulerStatus(BaseModel):
    running: bool
    scalping_interval_sec: int
    daily_interval_sec: int


@router.get("/scheduler", response_model=SchedulerStatus)
def get_scheduler_status() -> SchedulerStatus:
    from engine.strategy.scheduler import status
    s = status()
    return SchedulerStatus(**s)


@router.post("/scheduler/start", response_model=SchedulerStatus)
def start_scheduler() -> SchedulerStatus:
    from engine.strategy.scheduler import start, status
    start()
    return SchedulerStatus(**status())


@router.post("/scheduler/stop", response_model=SchedulerStatus)
def stop_scheduler() -> SchedulerStatus:
    from engine.strategy.scheduler import stop, status
    stop()
    return SchedulerStatus(**status())

"""FastAPI application entry point for the Trading Strategy Engine."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import alerts, backtests, bot_config, knowledge, regime, screener, strategies, symbols

app = FastAPI(
    title="Trading Strategy Engine API",
    description="REST API for strategy management, backtesting, and knowledge base access.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup() -> None:
    from engine.core.database import init_db
    from engine.data.provider_crypto import warm_exchange_symbol_caches
    init_db()
    warm_exchange_symbol_caches()

    # Auto-start the modular Discord control bot when a token is configured.
    from engine.interfaces.discord import run_bot_background
    from engine.interfaces.scanner import run_alert_scanner_background
    run_bot_background()
    run_alert_scanner_background()

app.include_router(strategies.router, prefix="/api")
app.include_router(backtests.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(symbols.router, prefix="/api")
app.include_router(regime.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(screener.router, prefix="/api")
app.include_router(bot_config.router, prefix="/api")

@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}

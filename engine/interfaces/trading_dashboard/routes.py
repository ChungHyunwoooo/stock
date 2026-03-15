"""대시보드 API 라우터."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from engine.interfaces.trading_dashboard.services import (
    fetch_candles,
    get_alt_state,
    get_btc_state,
    get_history,
    get_symbols,
)
from engine.interfaces.trading_dashboard.template import HTML_TEMPLATE

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE


@router.get("/api/candles/{timeframe}")
async def api_candles(timeframe: str = "1h", limit: int = 200,
                      before: int | None = None, symbol: str = "BTC/USDT"):
    if before:
        import pandas as pd
        end = pd.Timestamp(before, unit="s", tz="UTC")
        tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}
        hours = tf_hours.get(timeframe, 1) * (limit + 60)
        start = end - pd.Timedelta(hours=hours)
        from engine.interfaces.trading_dashboard.services import _provider
        import numpy as np, talib
        df = _provider.fetch_ohlcv(symbol, str(start), str(end), timeframe)
        close = df["close"].values.astype(np.float64)
        ema20 = talib.EMA(close, timeperiod=20)
        ema50 = talib.EMA(close, timeperiod=50)
        rsi = talib.RSI(close, timeperiod=14)
        candles = []
        for i, (ts, row) in enumerate(df.iterrows()):
            t = int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(pd.Timestamp(ts).timestamp())
            candles.append({
                "time": t, "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": float(row["volume"]),
                "ema20": float(ema20[i]) if not np.isnan(ema20[i]) else None,
                "ema50": float(ema50[i]) if not np.isnan(ema50[i]) else None,
                "rsi": round(float(rsi[i]), 2) if not np.isnan(rsi[i]) else None,
            })
        return candles[-limit:]
    return fetch_candles(timeframe, limit, symbol)


@router.get("/api/state")
async def api_state():
    return get_btc_state()


@router.get("/api/symbols")
async def api_symbols():
    return get_symbols()


@router.get("/api/alt_state")
async def api_alt_state():
    return get_alt_state()


@router.get("/api/history")
async def api_history():
    return get_history()


@router.websocket("/ws/candles/{timeframe}")
async def ws_candles(websocket: WebSocket, timeframe: str = "1h", symbol: str = "BTC/USDT"):
    await websocket.accept()
    try:
        while True:
            candles = fetch_candles(timeframe, 2, symbol)
            if candles:
                await websocket.send_json({"type": "candle", "data": candles[-1]})

            from engine.interfaces.trading_dashboard.services import read_bot_state
            from engine.data.provider_crypto import fetch_funding_rate
            state = read_bot_state()
            fr = fetch_funding_rate("BTC/USDT:USDT")
            await websocket.send_json({"type": "state", "data": {
                "position": state.get("position"),
                "cooldown_until": state.get("cooldown_until", ""),
                "trades": len(state.get("trade_log", [])),
                "current_fr": fr,
            }})

            intervals = {"1m": 10, "5m": 30, "15m": 60, "1h": 60, "4h": 120}
            await asyncio.sleep(intervals.get(timeframe, 60))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

"""BTC_선물_봇 트레이딩 대시보드 — FastAPI + lightweight-charts.

실행:
    .venv/bin/python -m engine.interfaces.trading_dashboard.app
    → http://localhost:8501
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from engine.data.provider_crypto import CryptoProvider, fetch_funding_rate

logger = logging.getLogger(__name__)

app = FastAPI(title="BTC_선물_봇 Dashboard")

ROOT = Path(__file__).resolve().parents[3]
STATE_FILE = ROOT / "state" / "funding_contrarian_state.json"
ALT_STATE_FILE = ROOT / "state" / "alt_momentum_state.json"

_provider = CryptoProvider("binance")


def _read_bot_state() -> dict:
    """봇 상태 파일 읽기."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"position": None, "cooldown_remaining": 0, "fr_history": [], "trade_log": []}


def _fetch_candles(timeframe: str = "1h", limit: int = 200, symbol: str = "BTC/USDT") -> list[dict]:
    """바이낸스에서 캔들 + 지표 데이터."""
    import pandas as pd
    import talib
    end = pd.Timestamp.now(tz="UTC")
    tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}
    hours = tf_hours.get(timeframe, 1) * (limit + 60)
    start = end - pd.Timedelta(hours=hours)
    df = _provider.fetch_ohlcv(symbol, str(start), str(end), timeframe)

    close = df["close"].values.astype(np.float64)
    ema20 = talib.EMA(close, timeperiod=20)
    ema50 = talib.EMA(close, timeperiod=50)
    rsi = talib.RSI(close, timeperiod=14)

    candles = []
    for i, (ts, row) in enumerate(df.iterrows()):
        t = int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(pd.Timestamp(ts).timestamp())
        candles.append({
            "time": t,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "ema20": float(ema20[i]) if not np.isnan(ema20[i]) else None,
            "ema50": float(ema50[i]) if not np.isnan(ema50[i]) else None,
            "rsi": round(float(rsi[i]), 2) if not np.isnan(rsi[i]) else None,
        })
    # limit만큼만 반환
    return candles[-limit:]


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE


@app.get("/api/candles/{timeframe}")
async def get_candles(timeframe: str = "1h", limit: int = 200, before: int | None = None, symbol: str = "BTC/USDT"):
    """캔들 조회. before=timestamp면 해당 시점 이전 데이터."""
    if before:
        import pandas as pd
        end = pd.Timestamp(before, unit="s", tz="UTC")
        tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}
        hours = tf_hours.get(timeframe, 1) * (limit + 60)
        start = end - pd.Timedelta(hours=hours)
        df = _provider.fetch_ohlcv(symbol, str(start), str(end), timeframe)
        import talib
        close = df["close"].values.astype(np.float64)
        ema20 = talib.EMA(close, timeperiod=20)
        ema50 = talib.EMA(close, timeperiod=50)
        rsi = talib.RSI(close, timeperiod=14)
        candles = []
        for i, (ts, row) in enumerate(df.iterrows()):
            t = int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(pd.Timestamp(ts).timestamp())
            candles.append({
                "time": t, "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"]),
                "ema20": float(ema20[i]) if not np.isnan(ema20[i]) else None,
                "ema50": float(ema50[i]) if not np.isnan(ema50[i]) else None,
                "rsi": round(float(rsi[i]), 2) if not np.isnan(rsi[i]) else None,
            })
        return candles[-limit:]
    return _fetch_candles(timeframe, limit, symbol)


@app.get("/api/state")
async def get_state():
    state = _read_bot_state()
    fr = fetch_funding_rate("BTC/USDT:USDT")
    # z-score 계산
    fr_history = state.get("fr_history", [])
    zscore = None
    if len(fr_history) >= 150:
        window = fr_history[-150:]
        mean = np.mean(window)
        std = np.std(window)
        if std > 1e-10 and fr is not None:
            zscore = round((fr - mean) / std, 2)

    return {
        "position": state.get("position"),
        "cooldown": state.get("cooldown_remaining", 0),
        "trade_log": state.get("trade_log", [])[-20:],
        "fr_history_len": len(fr_history),
        "current_fr": fr,
        "fr_zscore": zscore,
        "last_updated": state.get("last_updated"),
    }


@app.get("/api/symbols")
async def get_symbols():
    """거래 가능한 심볼 목록 (기본 + 알트봇 종목 + 거래이력 종목)."""
    syms = {"BTC/USDT"}
    # 알트봇 설정 종목
    try:
        from engine.strategy.alt_momentum import VALIDATED_SYMBOLS
        syms.update(VALIDATED_SYMBOLS)
    except Exception:
        pass
    # 거래이력 종목
    if ALT_STATE_FILE.exists():
        try:
            data = json.loads(ALT_STATE_FILE.read_text())
            for t in data.get("trade_log", []):
                if t.get("symbol"): syms.add(t["symbol"])
            for p in data.get("positions", []):
                if p.get("symbol"): syms.add(p["symbol"])
        except Exception:
            pass
    return sorted(syms)


@app.get("/api/alt_state")
async def get_alt_state():
    """알트_데일리_봇 상태."""
    if ALT_STATE_FILE.exists():
        try:
            data = json.loads(ALT_STATE_FILE.read_text())
            positions = data.get("positions", [])
            trade_log = data.get("trade_log", [])[-30:]
            pnls = [t["pnl_pct"] for t in trade_log] if trade_log else []
            wins = [p for p in pnls if p > 0]
            return {
                "positions": positions,
                "position_count": len(positions),
                "trade_log": trade_log,
                "total_trades": len(data.get("trade_log", [])),
                "wins": len(wins),
                "win_rate": round(len(wins)/len(pnls)*100, 1) if pnls else 0,
                "avg_pnl": round(float(np.mean(pnls)), 3) if pnls else 0,
                "cumulative": round(sum(pnls), 2) if pnls else 0,
                "last_updated": data.get("last_updated"),
            }
        except Exception:
            pass
    return {"positions": [], "position_count": 0, "trade_log": [], "total_trades": 0}


@app.get("/api/history")
async def get_history():
    """통합 매매 히스토리 (BTC봇 + 알트봇)."""
    trades = []

    # BTC봇
    btc_state = _read_bot_state()
    for t in btc_state.get("trade_log", []):
        trades.append({
            "bot": "BTC_선물_봇",
            "symbol": t.get("symbol", "BTC/USDT"),
            "side": t.get("side", ""),
            "entry": t.get("entry", 0),
            "exit": t.get("exit", 0),
            "pnl": t.get("pnl_pct_lev", t.get("pnl_pct", 0)),
            "bars": t.get("bars_held", 0),
            "reason": t.get("reason", ""),
            "entry_time": t.get("entry_time", ""),
            "exit_time": t.get("exit_time", ""),
        })

    # 알트봇
    if ALT_STATE_FILE.exists():
        try:
            alt_data = json.loads(ALT_STATE_FILE.read_text())
            for t in alt_data.get("trade_log", []):
                trades.append({
                    "bot": "알트_데일리_봇",
                    "symbol": t.get("symbol", ""),
                    "side": t.get("side", "LONG"),
                    "entry": t.get("entry", 0),
                    "exit": t.get("exit", 0),
                    "pnl": t.get("pnl_pct", 0),
                    "bars": t.get("bars_held", 0),
                    "reason": t.get("reason", ""),
                    "entry_time": t.get("entry_time", ""),
                    "exit_time": t.get("exit_time", ""),
                })
        except Exception:
            pass

    # 시간순 정렬 (최신 먼저)
    trades.sort(key=lambda x: x.get("exit_time", ""), reverse=True)

    # 통계
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    stats = {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins)/len(pnls)*100, 1) if pnls else 0,
        "avg_pnl": round(float(np.mean(pnls)), 3) if pnls else 0,
        "cumulative": round(sum(pnls), 2) if pnls else 0,
        "best": round(max(pnls), 2) if pnls else 0,
        "worst": round(min(pnls), 2) if pnls else 0,
    }

    return {"trades": trades[:100], "stats": stats}


@app.websocket("/ws/candles/{timeframe}")
async def ws_candles(websocket: WebSocket, timeframe: str = "1h", symbol: str = "BTC/USDT"):
    """실시간 캔들 스트리밍."""
    await websocket.accept()
    try:
        while True:
            candles = _fetch_candles(timeframe, 2, symbol)
            if candles:
                await websocket.send_json({"type": "candle", "data": candles[-1]})
            state = _read_bot_state()
            fr = fetch_funding_rate("BTC/USDT:USDT")
            await websocket.send_json({"type": "state", "data": {
                "position": state.get("position"),
                "cooldown": state.get("cooldown_remaining", 0),
                "trades": len(state.get("trade_log", [])),
                "current_fr": fr,
            }})
            # TF별 업데이트 간격
            intervals = {"1m": 10, "5m": 30, "15m": 60, "1h": 60, "4h": 120}
            await asyncio.sleep(intervals.get(timeframe, 60))
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# HTML 템플릿 (바이낸스 다크 테마 + lightweight-charts)
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>₿</text></svg>">
<title>BTC_선물_봇 Dashboard</title>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0b0e11; color:#eaecef; font-family:'Inter',sans-serif; font-size:13px; }

.header {
    display:flex; align-items:center; justify-content:space-between;
    padding:8px 16px; background:#1e2329; border-bottom:1px solid #2b3139;
}
.header .symbol { font-size:20px; font-weight:700; color:#f0b90b; }
.header .price { font-size:24px; font-weight:700; margin-left:16px; }
.header .price.up { color:#0ecb81; }
.header .price.down { color:#f6465d; }
.header .info { display:flex; gap:24px; font-size:12px; color:#848e9c; }
.header .info span { display:flex; flex-direction:column; }
.header .info .label { color:#848e9c; font-size:10px; }
.header .info .value { color:#eaecef; font-size:13px; font-weight:600; }
.header .info .value.positive { color:#0ecb81; }
.header .info .value.negative { color:#f6465d; }
.header .info .value.warning { color:#f0b90b; }

.tf-buttons {
    display:flex; gap:4px; padding:8px 16px; background:#1e2329;
}
.tf-btn {
    padding:4px 12px; border:none; border-radius:4px; cursor:pointer;
    background:#2b3139; color:#848e9c; font-size:12px;
}
.tf-btn.active { background:#f0b90b; color:#0b0e11; font-weight:700; }

.main { display:flex; height:calc(100vh - 140px); }

.chart-area { flex:1; position:relative; }
#chart { width:100%; height:100%; }

.panel {
    width:320px; background:#1e2329; border-left:1px solid #2b3139;
    overflow-y:auto; padding:16px;
}
.panel h3 { color:#f0b90b; font-size:14px; margin-bottom:12px; border-bottom:1px solid #2b3139; padding-bottom:8px; }
.panel .row { display:flex; justify-content:space-between; padding:4px 0; }
.panel .row .label { color:#848e9c; }
.panel .row .val { color:#eaecef; font-weight:600; }
.panel .row .val.long { color:#0ecb81; }
.panel .row .val.short { color:#f6465d; }
.panel .row .val.warn { color:#f0b90b; }

.status-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
.status-dot.green { background:#0ecb81; }
.status-dot.red { background:#f6465d; }
.status-dot.yellow { background:#f0b90b; }

.trade-table { width:100%; border-collapse:collapse; margin-top:8px; font-size:11px; }
.trade-table th { text-align:left; color:#848e9c; padding:4px 2px; border-bottom:1px solid #2b3139; }
.trade-table td { padding:4px 2px; border-bottom:1px solid #1e2329; }
.trade-table .win { color:#0ecb81; }
.trade-table .loss { color:#f6465d; }

.footer {
    display:flex; justify-content:space-around; padding:8px 16px;
    background:#1e2329; border-top:1px solid #2b3139;
}
.footer .stat { text-align:center; }
.footer .stat .label { color:#848e9c; font-size:10px; }
.footer .stat .val { font-size:16px; font-weight:700; }
</style>
</head>
<body>

<div class="header">
    <div style="display:flex;align-items:center;gap:8px;">
        <select id="symbol-select" style="background:#2b3139;color:#f0b90b;border:1px solid #2b3139;padding:4px 8px;font-size:16px;font-weight:700;border-radius:4px;cursor:pointer;">
            <option value="BTC/USDT">BTC/USDT</option>
        </select>
        <span class="price up" id="hdr-price">--</span>
    </div>
    <div class="info">
        <span><span class="label">펀딩비</span><span class="value" id="hdr-fr">--</span></span>
        <span><span class="label">FR z-score</span><span class="value" id="hdr-zscore">--</span></span>
        <span><span class="label">봇 상태</span><span class="value" id="hdr-status">--</span></span>
        <span><span class="label">BTC 모드</span><span class="value warning">PAPER 3x</span></span>
        <span><span class="label">알트봇</span><span class="value" id="hdr-alt" style="color:#3498db;">-</span></span>
    </div>
</div>

<div class="tf-buttons">
    <button class="tf-btn" data-tf="1m">1m</button>
    <button class="tf-btn" data-tf="5m">5m</button>
    <button class="tf-btn" data-tf="15m">15m</button>
    <button class="tf-btn active" data-tf="1h">1H</button>
    <button class="tf-btn" data-tf="4h">4H</button>
    <button class="tf-btn" data-tf="1d">1D</button>
</div>

<div class="main">
    <div class="chart-area">
        <div id="chart" style="height:calc(100% - 100px);"></div>
        <div id="rsi-chart" style="height:80px;border-top:1px solid #2b3139;"></div>
        <div id="sync-bar" style="height:20px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;background:#1e2329;border-top:1px solid #2b3139;font-size:10px;color:#848e9c;">
            <span>마지막 동기화: <span id="sync-time">-</span></span>
            <span>다음 동기화: <span id="sync-countdown">-</span></span>
            <span id="cooldown-bar" style="color:#f0b90b;display:none;">쿨다운 <span id="cd-remain">0</span>/24h</span>
        </div>
    </div>
    <div class="panel">
        <h3>포지션</h3>
        <div id="position-panel">
            <div class="row"><span class="label">상태</span><span class="val" id="pos-status">관망 중</span></div>
            <div class="row"><span class="label">방향</span><span class="val" id="pos-side">-</span></div>
            <div class="row"><span class="label">진입가</span><span class="val" id="pos-entry">-</span></div>
            <div class="row"><span class="label">손절가</span><span class="val" id="pos-sl">-</span></div>
            <div class="row"><span class="label">보유</span><span class="val" id="pos-hold">-</span></div>
            <div class="row"><span class="label">쿨다운</span><span class="val" id="pos-cd">-</span></div>
        </div>

        <h3 style="margin-top:20px;">펀딩비</h3>
        <div>
            <div class="row"><span class="label">현재 FR</span><span class="val" id="fr-current">-</span></div>
            <div class="row"><span class="label">z-score</span><span class="val" id="fr-zscore">-</span></div>
            <div class="row"><span class="label">임계값</span><span class="val">±1.5</span></div>
            <div class="row"><span class="label">히스토리</span><span class="val" id="fr-count">-</span></div>
        </div>

        <h3 style="margin-top:20px;">BTC 거래 이력</h3>
        <table class="trade-table">
            <thead><tr><th>#</th><th>방향</th><th>PnL(3x)</th><th>사유</th></tr></thead>
            <tbody id="trade-tbody"></tbody>
        </table>

        <h3 style="margin-top:24px;color:#3498db;">알트_데일리_봇</h3>
        <div>
            <div class="row"><span class="label">상태</span><span class="val" id="alt-status">-</span></div>
            <div class="row"><span class="label">포지션</span><span class="val" id="alt-pos-count">0/5</span></div>
            <div class="row"><span class="label">총 거래</span><span class="val" id="alt-trades">0</span></div>
            <div class="row"><span class="label">승률</span><span class="val" id="alt-winrate">-</span></div>
            <div class="row"><span class="label">누적 PnL</span><span class="val" id="alt-pnl">0%</span></div>
        </div>
        <div id="alt-positions" style="margin-top:8px;"></div>
        <table class="trade-table" style="margin-top:8px;">
            <thead><tr><th>심볼</th><th>PnL</th><th>사유</th></tr></thead>
            <tbody id="alt-trade-tbody"></tbody>
        </table>
    </div>
</div>

<div class="footer" style="cursor:pointer;" onclick="toggleHistory()">
    <div class="stat"><div class="label">BTC 거래</div><div class="val" id="ft-trades">0</div></div>
    <div class="stat"><div class="label">BTC 승률</div><div class="val" id="ft-winrate">-</div></div>
    <div class="stat"><div class="label">BTC PnL</div><div class="val" id="ft-pnl">0%</div></div>
    <div class="stat"><div class="label">알트 거래</div><div class="val" id="ft-alt-trades">0</div></div>
    <div class="stat"><div class="label">알트 PnL</div><div class="val" id="ft-alt-pnl">0%</div></div>
    <div class="stat"><div class="label">▲ 히스토리</div><div class="val" id="ft-updated">-</div></div>
</div>

<div id="history-panel" style="display:none;background:#1e2329;border-top:1px solid #2b3139;max-height:300px;overflow-y:auto;padding:8px 16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <h3 style="color:#f0b90b;font-size:14px;margin:0;">전체 매매 히스토리</h3>
        <div style="display:flex;gap:4px;">
            <button class="tf-btn active" onclick="filterHistory('all')" id="hf-all">전체</button>
            <button class="tf-btn" onclick="filterHistory('btc')" id="hf-btc">BTC봇</button>
            <button class="tf-btn" onclick="filterHistory('alt')" id="hf-alt">알트봇</button>
            <button class="tf-btn" onclick="filterHistory('win')" id="hf-win">승</button>
            <button class="tf-btn" onclick="filterHistory('loss')" id="hf-loss">패</button>
        </div>
    </div>
    <table class="trade-table" style="font-size:12px;">
        <thead><tr>
            <th>시간</th><th>봇</th><th>심볼</th><th>방향</th>
            <th>진입</th><th>청산</th><th>PnL</th><th>보유</th><th>사유</th>
        </tr></thead>
        <tbody id="history-tbody"></tbody>
    </table>
    <div id="history-stats" style="margin-top:8px;padding:8px;background:#0b0e11;border-radius:4px;font-size:11px;display:flex;gap:24px;"></div>
</div>

<script>
// === 메인 차트 (캔들 + EMA + 볼륨) ===
const chartEl = document.getElementById('chart');
const chart = LightweightCharts.createChart(chartEl, {
    layout: { background:{type:'solid',color:'#0b0e11'}, textColor:'#848e9c' },
    grid: { vertLines:{color:'#1e2329'}, horzLines:{color:'#1e2329'} },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor:'#2b3139' },
    timeScale: { borderColor:'#2b3139', timeVisible:true },
});
const candleSeries = chart.addCandlestickSeries({
    upColor:'#0ecb81', downColor:'#f6465d',
    borderUpColor:'#0ecb81', borderDownColor:'#f6465d',
    wickUpColor:'#0ecb81', wickDownColor:'#f6465d',
});
const ema20Series = chart.addLineSeries({ color:'#f0b90b', lineWidth:1, title:'EMA20' });
const ema50Series = chart.addLineSeries({ color:'#3498db', lineWidth:1, title:'EMA50' });
const volumeSeries = chart.addHistogramSeries({
    priceFormat:{type:'volume'}, priceScaleId:'vol',
});
chart.priceScale('vol').applyOptions({scaleMargins:{top:0.85,bottom:0}});

// === RSI 서브차트 ===
const rsiEl = document.getElementById('rsi-chart');
const rsiChart = LightweightCharts.createChart(rsiEl, {
    layout: { background:{type:'solid',color:'#0b0e11'}, textColor:'#848e9c' },
    grid: { vertLines:{color:'#1e2329'}, horzLines:{color:'#1e2329'} },
    rightPriceScale: { borderColor:'#2b3139' },
    timeScale: { visible:false },
    height: 80,
});
const rsiSeries = rsiChart.addLineSeries({ color:'#e6a307', lineWidth:1, title:'RSI(14)' });
// RSI 70/30 라인
const rsi70 = rsiChart.addLineSeries({color:'#f6465d33',lineWidth:1,lineStyle:2});
const rsi30 = rsiChart.addLineSeries({color:'#0ecb8133',lineWidth:1,lineStyle:2});

let currentTF = '1h';
let ws = null;
let entryPriceLine = null;
let slPriceLine = null;

let allCandles = [];
let loadingMore = false;
let currentSymbol = 'BTC/USDT';

async function loadCandles(tf) {
    const res = await fetch('/api/candles/' + tf + '?limit=500&symbol=' + encodeURIComponent(currentSymbol));
    const data = await res.json();
    allCandles = data;
    renderCandles(data);
    await loadTradeMarkers(data);
    updateSyncTime();
}

function renderCandles(data) {
    candleSeries.setData(data.map(c=>({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close})));
    volumeSeries.setData(data.map(c=>({time:c.time,value:c.volume,color:c.close>=c.open?'rgba(14,203,129,0.3)':'rgba(246,70,93,0.3)'})));
    // EMA
    ema20Series.setData(data.filter(c=>c.ema20).map(c=>({time:c.time,value:c.ema20})));
    ema50Series.setData(data.filter(c=>c.ema50).map(c=>({time:c.time,value:c.ema50})));
    // RSI
    const rsiData = data.filter(c=>c.rsi).map(c=>({time:c.time,value:c.rsi}));
    rsiSeries.setData(rsiData);
    rsi70.setData(rsiData.map(c=>({time:c.time,value:70})));
    rsi30.setData(rsiData.map(c=>({time:c.time,value:30})));
    if(data.length) {
        document.getElementById('hdr-price').textContent = '$' + data[data.length-1].close.toLocaleString();
        document.getElementById('hdr-price').className = 'price ' + (data[data.length-1].close >= data[data.length-1].open ? 'up' : 'down');
    }
}

// 스크롤 시 과거 봉 자동 로드 (디바운스)
let scrollTimer = null;
chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if(!range || loadingMore) return;
    if(range.from < 10 && allCandles.length > 0) {
        if(scrollTimer) clearTimeout(scrollTimer);
        scrollTimer = setTimeout(async () => {
            loadingMore = true;
            const oldest = allCandles[0].time;
            try {
                const res = await fetch('/api/candles/' + currentTF + '?limit=500&before=' + oldest + '&symbol=' + encodeURIComponent(currentSymbol));
                const older = await res.json();
                if(older.length > 0) {
                    const filtered = older.filter(c => c.time < oldest);
                    if(filtered.length > 0) {
                        allCandles = [...filtered, ...allCandles];
                        renderCandles(allCandles);
                    }
                }
            } catch(e) {}
            loadingMore = false;
        }, 500);
    }
});

// 동기화 시간
let lastSyncTime = null;
let syncInterval = 60;
function updateSyncTime() {
    lastSyncTime = new Date();
    document.getElementById('sync-time').textContent = lastSyncTime.toLocaleTimeString('ko-KR');
}
setInterval(() => {
    if(!lastSyncTime) return;
    const elapsed = Math.floor((Date.now() - lastSyncTime.getTime()) / 1000);
    const remain = Math.max(0, syncInterval - elapsed);
    document.getElementById('sync-countdown').textContent = remain + 's';
}, 1000);

async function loadTradeMarkers(candleData) {
    const stateRes = await fetch('/api/state');
    const state = await stateRes.json();
    const trades = state.trade_log || [];

    const markers = [];

    // 과거 거래: B/S 진입 + 청산 마커
    trades.forEach(t => {
        if(!t.entry_time) return;
        const entryTs = Math.floor(new Date(t.entry_time).getTime()/1000);
        const exitTs = t.exit_time ? Math.floor(new Date(t.exit_time).getTime()/1000) : null;
        const isWin = t.pnl_pct_lev > 0;
        const isLong = t.side === 'LONG';

        // 진입: B or S
        markers.push({
            time: entryTs,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#0ecb81' : '#f6465d',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: (isLong ? 'B' : 'S') + ' ' + (isWin?'+':'') + t.pnl_pct_lev + '%',
        });

        // 청산: X 마커
        if(exitTs) {
            markers.push({
                time: exitTs,
                position: isLong ? 'aboveBar' : 'belowBar',
                color: isWin ? '#0ecb81' : '#f6465d',
                shape: 'circle',
                text: (isWin?'✓':'✗') + ' ' + t.reason,
            });
        }
    });

    // 현재 포지션: 활성 B/S
    const pos = state.position;
    if(pos && candleData.length) {
        const entryTs = pos.entry_time ? Math.floor(new Date(pos.entry_time).getTime()/1000) : candleData[candleData.length-1].time;
        markers.push({
            time: entryTs,
            position: pos.side==='LONG' ? 'belowBar' : 'aboveBar',
            color: '#f0b90b',
            shape: pos.side==='LONG' ? 'arrowUp' : 'arrowDown',
            text: (pos.side==='LONG'?'B':'S') + ' ACTIVE ' + pos.bars_held + '/' + pos.max_hold + 'h',
        });
    }

    markers.sort((a,b) => a.time - b.time);
    if(markers.length) candleSeries.setMarkers(markers);

    // 쿨다운 영역 표시 (진입~청산 후 24h를 배경색으로)
    updateCooldownZones(trades, candleData);
}

function updateCooldownZones(trades, candleData) {
    // 기존 쿨다운 시리즈 제거 후 재생성
    if(window._cdSeries) { chart.removeSeries(window._cdSeries); window._cdSeries=null; }
    if(!trades.length || !candleData.length) return;

    // 쿨다운 구간: 청산 시점 ~ 청산+24h
    const cdData = [];
    const minTime = candleData[0].time;
    const maxTime = candleData[candleData.length-1].time;

    trades.forEach(t => {
        if(!t.exit_time) return;
        const exitTs = Math.floor(new Date(t.exit_time).getTime()/1000);
        const cdEnd = exitTs + 24*3600; // 24h 쿨다운
        // 캔들 데이터 범위 내의 쿨다운만
        candleData.forEach(c => {
            if(c.time >= exitTs && c.time <= cdEnd) {
                cdData.push({time: c.time, value: c.high * 1.001, color: 'rgba(240,185,11,0.08)'});
            }
        });
    });

    if(cdData.length > 0) {
        // 중복 제거 (시간 기준)
        const unique = {};
        cdData.forEach(d => { if(!unique[d.time]) unique[d.time] = d; });
        const sorted = Object.values(unique).sort((a,b) => a.time - b.time);
        window._cdSeries = chart.addHistogramSeries({
            priceScaleId: 'cd', color: 'rgba(240,185,11,0.08)',
            priceFormat: {type:'price'}, lastValueVisible:false, priceLineVisible:false,
        });
        chart.priceScale('cd').applyOptions({scaleMargins:{top:0,bottom:0}, visible:false});
        window._cdSeries.setData(sorted);
    }
}

function updatePositionLines(pos) {
    // 이전 라인 제거
    if(entryPriceLine) { candleSeries.removePriceLine(entryPriceLine); entryPriceLine = null; }
    if(slPriceLine) { candleSeries.removePriceLine(slPriceLine); slPriceLine = null; }

    if(!pos) return;

    // 진입가 라인 (초록=롱, 빨강=숏)
    entryPriceLine = candleSeries.createPriceLine({
        price: pos.entry_price,
        color: pos.side==='LONG' ? '#0ecb81' : '#f6465d',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: pos.side + ' Entry $' + pos.entry_price.toLocaleString(),
    });

    // 손절가 라인 (빨강 점선)
    slPriceLine = candleSeries.createPriceLine({
        price: pos.stop_loss,
        color: '#f6465d',
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL $' + pos.stop_loss.toLocaleString(),
    });
}

var wsTimer = null;
function connectWS(tf) {
    if(ws) { try{ws.close();}catch(e){} ws=null; }
    if(wsTimer) clearTimeout(wsTimer);
    wsTimer = setTimeout(function() {
        ws = new WebSocket('ws://'+location.host+'/ws/candles/'+tf+'?symbol='+encodeURIComponent(currentSymbol));
    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            if(msg.type==='candle') {
                const c = msg.data;
                candleSeries.update({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close});
                volumeSeries.update({time:c.time,value:c.volume,color:c.close>=c.open?'rgba(14,203,129,0.3)':'rgba(246,70,93,0.3)'});
                document.getElementById('hdr-price').textContent = '$' + c.close.toLocaleString();
            }
            if(msg.type==='state') updateState(msg.data);
        } catch(err) {}
    };
    ws.onerror = function(){};
    ws.onclose = function(){ setTimeout(function(){connectWS(tf);}, 5000); };
    }, 300);
}

async function loadState() {
    const res = await fetch('/api/state');
    const s = await res.json();
    updateFullState(s);
}

function updateState(s) {
    document.getElementById('ft-trades').textContent = s.trades || 0;
    if(s.current_fr !== null) {
        document.getElementById('hdr-fr').textContent = (s.current_fr*100).toFixed(4) + '%';
    }
}

function updateFullState(s) {
    // FR
    if(s.current_fr !== null) {
        const frEl = document.getElementById('fr-current');
        frEl.textContent = (s.current_fr*100).toFixed(4) + '%';
        document.getElementById('hdr-fr').textContent = (s.current_fr*100).toFixed(4) + '%';
    }
    if(s.fr_zscore !== null) {
        const zEl = document.getElementById('fr-zscore');
        const hzEl = document.getElementById('hdr-zscore');
        zEl.textContent = s.fr_zscore;
        hzEl.textContent = s.fr_zscore;
        zEl.className = 'val' + (Math.abs(s.fr_zscore)>1.5?' warn':'');
        hzEl.className = 'value' + (Math.abs(s.fr_zscore)>1.5?' warning':'');
    }
    document.getElementById('fr-count').textContent = s.fr_history_len;

    // Position + 차트 라인
    const pos = s.position;
    updatePositionLines(pos);
    if(pos) {
        document.getElementById('pos-status').innerHTML = '<span class="status-dot red"></span>포지션 보유';
        document.getElementById('pos-side').textContent = pos.side;
        document.getElementById('pos-side').className = 'val ' + (pos.side==='LONG'?'long':'short');
        document.getElementById('pos-entry').textContent = '$' + pos.entry_price.toLocaleString();
        document.getElementById('pos-sl').textContent = '$' + pos.stop_loss.toLocaleString();
        document.getElementById('pos-hold').textContent = pos.bars_held + '/' + pos.max_hold + 'h';
        document.getElementById('hdr-status').innerHTML = '<span class="status-dot red"></span>' + pos.side;
    } else {
        document.getElementById('pos-status').innerHTML = '<span class="status-dot green"></span>관망 중';
        document.getElementById('pos-side').textContent = '-';
        document.getElementById('pos-side').className = 'val';
        document.getElementById('pos-entry').textContent = '-';
        document.getElementById('pos-sl').textContent = '-';
        document.getElementById('pos-hold').textContent = '-';
        document.getElementById('hdr-status').innerHTML = s.cooldown>0?
            '<span class="status-dot yellow"></span>쿨다운':'<span class="status-dot green"></span>대기';
    }
    document.getElementById('pos-cd').textContent = s.cooldown>0? s.cooldown+'h 남음':'없음';

    // 쿨다운 바
    const cdBar = document.getElementById('cooldown-bar');
    if(s.cooldown > 0) {
        cdBar.style.display = 'inline';
        document.getElementById('cd-remain').textContent = s.cooldown;
    } else {
        cdBar.style.display = 'none';
    }

    // Trade log
    const tbody = document.getElementById('trade-tbody');
    tbody.innerHTML = '';
    const trades = s.trade_log || [];
    trades.reverse().forEach((t,i) => {
        const cls = t.pnl_pct_lev > 0 ? 'win' : 'loss';
        tbody.innerHTML += '<tr><td>'+(trades.length-i)+'</td><td class="'+cls+'">'+t.side+'</td><td class="'+cls+'">'+(t.pnl_pct_lev>0?'+':'')+t.pnl_pct_lev+'%</td><td>'+t.reason+'</td></tr>';
    });

    // Footer stats
    document.getElementById('ft-trades').textContent = trades.length;
    if(trades.length > 0) {
        const wins = trades.filter(t=>t.pnl_pct_lev>0).length;
        document.getElementById('ft-winrate').textContent = (wins/trades.length*100).toFixed(1)+'%';
        const cum = trades.reduce((s,t)=>s+t.pnl_pct_lev, 0);
        const pnlEl = document.getElementById('ft-pnl');
        pnlEl.textContent = (cum>0?'+':'')+cum.toFixed(1)+'%';
        pnlEl.style.color = cum>0?'#0ecb81':'#f6465d';
    }
    if(s.last_updated) {
        document.getElementById('ft-updated').textContent = new Date(s.last_updated).toLocaleTimeString('ko-KR');
    }
}

// TF buttons
document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tf-btn').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        currentTF = btn.dataset.tf;
        loadCandles(currentTF);
        connectWS(currentTF);
    });
});

// Resize
new ResizeObserver(() => {
    chart.applyOptions({width:chartEl.clientWidth,height:chartEl.clientHeight});
    rsiChart.applyOptions({width:rsiEl.clientWidth});
}).observe(chartEl);

// 메인↔RSI 시간축 동기화 (무한루프 방지)
let syncing = false;
chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if(syncing || !range) return;
    syncing = true;
    rsiChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
});

// 알트봇 상태 로드
async function loadAltState() {
    try {
        const res = await fetch('/api/alt_state');
        const s = await res.json();

        document.getElementById('hdr-alt').textContent = s.position_count>0? s.position_count+'포지션':'스캔중';
        document.getElementById('hdr-alt').style.color = s.position_count>0? '#f6465d':'#3498db';
        document.getElementById('alt-pos-count').textContent = s.position_count + '/5';
        document.getElementById('alt-trades').textContent = s.total_trades;
        document.getElementById('alt-winrate').textContent = s.win_rate ? s.win_rate+'%' : '-';

        const pnlEl = document.getElementById('alt-pnl');
        pnlEl.textContent = (s.cumulative>0?'+':'') + s.cumulative + '%';
        pnlEl.style.color = s.cumulative>=0 ? '#0ecb81' : '#f6465d';

        // 활성 포지션 상태
        if(s.position_count > 0) {
            document.getElementById('alt-status').innerHTML = '<span class="status-dot red"></span>' + s.position_count + '개 보유';
            let posHtml = '';
            s.positions.forEach(p => {
                posHtml += '<div style="font-size:11px;padding:2px 0;border-bottom:1px solid #2b3139;cursor:pointer;" data-sym="' + p.symbol + '" class="alt-pos-row">' +
                    '<span style="color:#f0b90b;">' + p.symbol + '</span> ' +
                    '<span style="color:#0ecb81;">LONG</span> ' +
                    '@' + p.entry_price.toFixed(4) + ' ' +
                    '<span style="color:#848e9c;">' + p.bars_held + '/' + p.max_hold + 'h</span></div>';
            });
            document.getElementById('alt-positions').innerHTML = posHtml;
        } else {
            document.getElementById('alt-status').innerHTML = '<span class="status-dot green"></span>스캔 중';
            document.getElementById('alt-positions').innerHTML = '';
        }

        // 알트 거래 이력
        const tbody = document.getElementById('alt-trade-tbody');
        tbody.innerHTML = '';
        (s.trade_log||[]).reverse().slice(0,10).forEach(t => {
            const cls = t.pnl_pct > 0 ? 'win' : 'loss';
            tbody.innerHTML += '<tr><td>' + t.symbol.replace('/USDT','') + '</td>' +
                '<td class="' + cls + '">' + (t.pnl_pct>0?'+':'') + t.pnl_pct + '%</td>' +
                '<td>' + t.reason + '</td></tr>';
        });
    } catch(e) {}
}

// 히스토리 패널
let allHistory = [];
let historyFilter = 'all';

function toggleHistory() {
    const panel = document.getElementById('history-panel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if(panel.style.display === 'block') loadHistory();
}

async function loadHistory() {
    const res = await fetch('/api/history');
    const data = await res.json();
    allHistory = data.trades || [];
    renderHistory();

    // 통계
    const s = data.stats;
    document.getElementById('history-stats').innerHTML =
        '<span>총 <b>' + s.total + '</b>건</span>' +
        '<span>승률 <b style="color:#0ecb81;">' + s.win_rate + '%</b></span>' +
        '<span>평균 <b>' + (s.avg_pnl>0?'+':'') + s.avg_pnl + '%</b></span>' +
        '<span>누적 <b style="color:' + (s.cumulative>=0?'#0ecb81':'#f6465d') + ';">' + (s.cumulative>0?'+':'') + s.cumulative + '%</b></span>' +
        '<span>최고 <b style="color:#0ecb81;">+' + s.best + '%</b></span>' +
        '<span>최저 <b style="color:#f6465d;">' + s.worst + '%</b></span>';

    // 푸터 알트 통계
    const altTrades = allHistory.filter(t => t.bot.includes('알트'));
    const altPnls = altTrades.map(t => t.pnl);
    document.getElementById('ft-alt-trades').textContent = altTrades.length;
    const altCum = altPnls.reduce((a,b)=>a+b, 0);
    const altEl = document.getElementById('ft-alt-pnl');
    altEl.textContent = (altCum>0?'+':'') + altCum.toFixed(1) + '%';
    altEl.style.color = altCum>=0 ? '#0ecb81' : '#f6465d';
}

function filterHistory(type) {
    historyFilter = type;
    document.querySelectorAll('#history-panel .tf-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('hf-' + type).classList.add('active');
    renderHistory();
}

function renderHistory() {
    let filtered = allHistory;
    if(historyFilter === 'btc') filtered = allHistory.filter(t => t.bot.includes('BTC'));
    else if(historyFilter === 'alt') filtered = allHistory.filter(t => t.bot.includes('알트'));
    else if(historyFilter === 'win') filtered = allHistory.filter(t => t.pnl > 0);
    else if(historyFilter === 'loss') filtered = allHistory.filter(t => t.pnl <= 0);

    const tbody = document.getElementById('history-tbody');
    tbody.innerHTML = '';
    filtered.slice(0, 50).forEach(t => {
        const cls = t.pnl > 0 ? 'win' : 'loss';
        const botTag = t.bot.includes('BTC') ? '<span style="color:#f0b90b;">BTC</span>' : '<span style="color:#3498db;">ALT</span>';
        const time = t.exit_time ? new Date(t.exit_time).toLocaleString('ko-KR', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '-';
        const sym = t.symbol.replace('/USDT','');
        const entry = typeof t.entry === 'number' ? t.entry.toFixed(t.entry>1000?0:4) : t.entry;
        const exit = typeof t.exit === 'number' ? t.exit.toFixed(t.exit>1000?0:4) : t.exit;
        const entryTs = t.entry_time ? Math.floor(new Date(t.entry_time).getTime()/1000) : 0;
        const exitTs = t.exit_time ? Math.floor(new Date(t.exit_time).getTime()/1000) : 0;
        tbody.innerHTML += '<tr style="cursor:pointer;" data-sym="' + t.symbol + '" data-entry="' + entryTs + '" data-exit="' + exitTs + '" data-side="' + t.side + '" data-pnl="' + t.pnl + '">' +
            '<td style="color:#848e9c;">' + time + '</td>' +
            '<td>' + botTag + '</td>' +
            '<td>' + sym + '</td>' +
            '<td class="' + cls + '">' + t.side + '</td>' +
            '<td>' + entry + '</td>' +
            '<td>' + exit + '</td>' +
            '<td class="' + cls + '">' + (t.pnl>0?'+':'') + t.pnl + '%</td>' +
            '<td style="color:#848e9c;">' + t.bars + 'h</td>' +
            '<td style="color:#848e9c;">' + t.reason + '</td></tr>';
    });
}

// 히스토리 테이블 클릭 이벤트 위임
document.getElementById('history-tbody').addEventListener('click', function(e) {
    var tr = e.target.closest('tr');
    if(!tr || !tr.dataset.sym) return;
    jumpToTrade(tr.dataset.sym, parseInt(tr.dataset.entry), parseInt(tr.dataset.exit), tr.dataset.side, parseFloat(tr.dataset.pnl));
});

// 알트 포지션 클릭 이벤트 위임
document.getElementById('alt-positions').addEventListener('click', function(e) {
    var row = e.target.closest('[data-sym]');
    if(!row) return;
    switchToSymbol(row.dataset.sym);
});

// 심볼 선택
document.getElementById('symbol-select').addEventListener('change', (e) => {
    currentSymbol = e.target.value;
    allCandles = [];
    loadCandles(currentTF);
    connectWS(currentTF);
});

// 알트 포지션 클릭 → 해당 차트로 전환
function switchToSymbol(sym) {
    // 현재 시간 범위 저장
    var savedRange = chart.timeScale().getVisibleLogicalRange();
    currentSymbol = sym;
    var sel = document.getElementById('symbol-select');
    if(!Array.from(sel.options).some(function(o){return o.value===sym;})) {
        var opt = document.createElement('option');
        opt.value = sym; opt.textContent = sym.replace('/USDT','');
        sel.appendChild(opt);
    }
    sel.value = sym;
    allCandles = [];

    fetch('/api/candles/' + currentTF + '?limit=500&symbol=' + encodeURIComponent(sym))
    .then(function(r) { return r.json(); })
    .then(function(data) {
        allCandles = data;
        renderCandles(data);
        // 시간 범위 복원
        if(savedRange) {
            try { chart.timeScale().setVisibleLogicalRange(savedRange); } catch(e) {}
        }
        updateSyncTime();
    });
    connectWS(currentTF);
}

function jumpToTrade(sym, entryTs, exitTs, side, pnl) {
    try {
        // 드롭다운에 없으면 추가
        const sel = document.getElementById('symbol-select');
        if(!Array.from(sel.options).some(o => o.value === sym)) {
            const opt = document.createElement('option');
            opt.value = sym; opt.textContent = sym.replace('/USDT','');
            sel.appendChild(opt);
        }

        // 캔들 로드 (기본 최근 500봉)
        currentSymbol = sym;
        sel.value = sym;

        fetch('/api/candles/' + currentTF + '?limit=500&symbol=' + encodeURIComponent(sym))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if(!data || !data.length) return;
            allCandles = data;
            renderCandles(data);

            // B/S 마커
            var isWin = pnl > 0;
            var markers = [];
            if(entryTs > 0) {
                markers.push({
                    time: entryTs,
                    position: side==='LONG' ? 'belowBar' : 'aboveBar',
                    color: '#f0b90b',
                    shape: side==='LONG' ? 'arrowUp' : 'arrowDown',
                    text: (side==='LONG'?'B':'S'),
                    size: 2,
                });
            }
            if(exitTs > 0) {
                markers.push({
                    time: exitTs,
                    position: side==='LONG' ? 'aboveBar' : 'belowBar',
                    color: isWin ? '#0ecb81' : '#f6465d',
                    shape: 'circle',
                    text: (pnl>0?'+':'') + pnl + '%',
                    size: 2,
                });
            }
            if(markers.length) {
                markers.sort(function(a,b) { return a.time - b.time; });
                candleSeries.setMarkers(markers);
            }

            // 스크롤: 캔들 데이터 범위 내에서만
            var from = entryTs - 20*3600;
            var to = (exitTs || entryTs) + 20*3600;
            var first = data[0].time;
            var last = data[data.length-1].time;
            if(from < first) from = first;
            if(to > last) to = last;
            chart.timeScale().setVisibleRange({from: from, to: to});
        })
        .catch(function(e) { console.error('jumpToTrade fetch error:', e); });
    } catch(e) { console.error('jumpToTrade error:', e); }
}

// 심볼 목록 자동 로드
async function loadSymbols() {
    try {
        const res = await fetch('/api/symbols');
        const syms = await res.json();
        const sel = document.getElementById('symbol-select');
        const current = sel.value;
        sel.innerHTML = '';
        syms.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s; opt.textContent = s.replace('/USDT','');
            sel.appendChild(opt);
        });
        sel.value = current || 'BTC/USDT';
    } catch(e) {}
}

// switchToSymbol: 드롭다운에 없는 심볼도 동적 추가
const origSwitch = switchToSymbol;
switchToSymbol = function(sym) {
    const sel = document.getElementById('symbol-select');
    if(!Array.from(sel.options).some(o => o.value === sym)) {
        const opt = document.createElement('option');
        opt.value = sym; opt.textContent = sym.replace('/USDT','');
        sel.appendChild(opt);
    }
    origSwitch(sym);
};

// Init
loadSymbols();
loadCandles(currentTF);
connectWS(currentTF);
loadState();
loadAltState();
setInterval(loadState, 30000);
setInterval(loadAltState, 30000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8501)

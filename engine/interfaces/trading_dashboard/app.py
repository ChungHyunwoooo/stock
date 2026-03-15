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

_provider = CryptoProvider("binance")


def _read_bot_state() -> dict:
    """봇 상태 파일 읽기."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"position": None, "cooldown_remaining": 0, "fr_history": [], "trade_log": []}


def _fetch_candles(timeframe: str = "1h", limit: int = 200) -> list[dict]:
    """바이낸스에서 캔들 데이터 가져오기."""
    import pandas as pd
    end = pd.Timestamp.now(tz="UTC")
    tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}
    hours = tf_hours.get(timeframe, 1) * limit
    start = end - pd.Timedelta(hours=hours)
    df = _provider.fetch_ohlcv("BTC/USDT", str(start), str(end), timeframe)
    candles = []
    for ts, row in df.iterrows():
        t = int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(pd.Timestamp(ts).timestamp())
        candles.append({
            "time": t,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })
    return candles


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE


@app.get("/api/candles/{timeframe}")
async def get_candles(timeframe: str = "1h", limit: int = 200):
    return _fetch_candles(timeframe, limit)


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


@app.websocket("/ws/candles/{timeframe}")
async def ws_candles(websocket: WebSocket, timeframe: str = "1h"):
    """실시간 캔들 스트리밍."""
    await websocket.accept()
    try:
        while True:
            candles = _fetch_candles(timeframe, 2)
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
    <div style="display:flex;align-items:center;">
        <span class="symbol">BTC/USDT</span>
        <span class="price up" id="hdr-price">--</span>
    </div>
    <div class="info">
        <span><span class="label">펀딩비</span><span class="value" id="hdr-fr">--</span></span>
        <span><span class="label">FR z-score</span><span class="value" id="hdr-zscore">--</span></span>
        <span><span class="label">봇 상태</span><span class="value" id="hdr-status">--</span></span>
        <span><span class="label">모드</span><span class="value warning">PAPER 3x</span></span>
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
    <div class="chart-area"><div id="chart"></div></div>
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

        <h3 style="margin-top:20px;">거래 이력</h3>
        <table class="trade-table">
            <thead><tr><th>#</th><th>방향</th><th>PnL(3x)</th><th>사유</th></tr></thead>
            <tbody id="trade-tbody"></tbody>
        </table>
    </div>
</div>

<div class="footer">
    <div class="stat"><div class="label">총 거래</div><div class="val" id="ft-trades">0</div></div>
    <div class="stat"><div class="label">승률</div><div class="val" id="ft-winrate">-</div></div>
    <div class="stat"><div class="label">누적 PnL</div><div class="val" id="ft-pnl">0%</div></div>
    <div class="stat"><div class="label">마지막 업데이트</div><div class="val" id="ft-updated">-</div></div>
</div>

<script>
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
const volumeSeries = chart.addHistogramSeries({
    priceFormat:{type:'volume'}, priceScaleId:'vol',
});
chart.priceScale('vol').applyOptions({scaleMargins:{top:0.8,bottom:0}});

let currentTF = '1h';
let ws = null;
let entryPriceLine = null;
let slPriceLine = null;

async function loadCandles(tf) {
    const res = await fetch('/api/candles/' + tf + '?limit=300');
    const data = await res.json();
    candleSeries.setData(data.map(c=>({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close})));
    volumeSeries.setData(data.map(c=>({time:c.time,value:c.volume,color:c.close>=c.open?'rgba(14,203,129,0.3)':'rgba(246,70,93,0.3)'})));
    if(data.length) document.getElementById('hdr-price').textContent = '$' + data[data.length-1].close.toLocaleString();
    // 과거 거래 마커
    await loadTradeMarkers(data);
}

async function loadTradeMarkers(candleData) {
    const stateRes = await fetch('/api/state');
    const state = await stateRes.json();
    const trades = state.trade_log || [];
    if(!trades.length || !candleData.length) return;

    const markers = [];
    trades.forEach(t => {
        if(!t.entry_time) return;
        const entryTs = Math.floor(new Date(t.entry_time).getTime()/1000);
        const exitTs = t.exit_time ? Math.floor(new Date(t.exit_time).getTime()/1000) : null;
        const isWin = t.pnl_pct_lev > 0;
        // 진입 마커
        markers.push({
            time: entryTs,
            position: t.side==='LONG' ? 'belowBar' : 'aboveBar',
            color: t.side==='LONG' ? '#0ecb81' : '#f6465d',
            shape: t.side==='LONG' ? 'arrowUp' : 'arrowDown',
            text: t.side + ' ' + (t.pnl_pct_lev>0?'+':'') + t.pnl_pct_lev + '%',
        });
        // 청산 마커
        if(exitTs) {
            markers.push({
                time: exitTs,
                position: 'inBar',
                color: isWin ? '#0ecb81' : '#f6465d',
                shape: 'circle',
                text: t.reason,
            });
        }
    });
    markers.sort((a,b) => a.time - b.time);
    if(markers.length) candleSeries.setMarkers(markers);
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

function connectWS(tf) {
    if(ws) ws.close();
    ws = new WebSocket('ws://'+location.host+'/ws/candles/'+tf);
    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if(msg.type==='candle') {
            const c = msg.data;
            candleSeries.update({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close});
            volumeSeries.update({time:c.time,value:c.volume,color:c.close>=c.open?'rgba(14,203,129,0.3)':'rgba(246,70,93,0.3)'});
            const priceEl = document.getElementById('hdr-price');
            priceEl.textContent = '$' + c.close.toLocaleString();
        }
        if(msg.type==='state') updateState(msg.data);
    };
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
new ResizeObserver(() => chart.applyOptions({width:chartEl.clientWidth,height:chartEl.clientHeight})).observe(chartEl);

// Init
loadCandles(currentTF);
connectWS(currentTF);
loadState();
setInterval(loadState, 30000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8501)

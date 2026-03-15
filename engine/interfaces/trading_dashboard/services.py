"""대시보드 데이터 서비스 — 캔들, 봇 상태, 심볼 조회."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import talib

from engine.data.provider_crypto import CryptoProvider, fetch_funding_rate

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
BTC_STATE_FILE = ROOT / "state" / "funding_contrarian_state.json"
ALT_STATE_FILE = ROOT / "state" / "alt_momentum_state.json"

_provider = CryptoProvider("binance")


def read_bot_state() -> dict:
    """BTC_선물_봇 상태 읽기."""
    if BTC_STATE_FILE.exists():
        try:
            return json.loads(BTC_STATE_FILE.read_text())
        except Exception as e:
            logger.warning("BTC 상태 파일 읽기 실패: %s", e)
    return {"position": None, "cooldown_until": "", "fr_history": [], "trade_log": []}


def read_alt_state() -> dict:
    """알트_데일리_봇 상태 읽기."""
    if ALT_STATE_FILE.exists():
        try:
            return json.loads(ALT_STATE_FILE.read_text())
        except Exception as e:
            logger.warning("알트 상태 파일 읽기 실패: %s", e)
    return {"positions": [], "trade_log": []}


def fetch_candles(timeframe: str = "1h", limit: int = 200, symbol: str = "BTC/USDT") -> list[dict]:
    """캔들 + 지표 데이터. 실패 시 빈 리스트."""
    try:
        return _fetch_candles_impl(timeframe, limit, symbol)
    except Exception as e:
        logger.warning("캔들 조회 실패 %s %s: %s", symbol, timeframe, e)
        return []


def _fetch_candles_impl(timeframe: str, limit: int, symbol: str) -> list[dict]:
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
    return candles[-limit:]


def get_btc_state() -> dict:
    """BTC봇 API 응답용 상태."""
    state = read_bot_state()
    fr_history = state.get("fr_history", [])
    fr = fetch_funding_rate("BTC/USDT:USDT")
    zscore = None
    if len(fr_history) >= 150:
        window = fr_history[-150:]
        mean = np.mean(window)
        std = np.std(window)
        if std > 1e-10 and fr is not None:
            zscore = round((fr - mean) / std, 2)

    return {
        "position": state.get("position"),
        "cooldown_until": state.get("cooldown_until", ""),
        "trade_log": state.get("trade_log", [])[-20:],
        "fr_history_len": len(fr_history),
        "current_fr": fr,
        "fr_zscore": zscore,
        "last_updated": state.get("last_updated"),
    }


def get_alt_state() -> dict:
    """알트봇 API 응답용 상태."""
    data = read_alt_state()
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


def get_symbols() -> list[str]:
    """사용 가능한 심볼 목록 (전체 바이낸스 선물)."""
    syms = set()
    # 전체 바이낸스 USDT-M 선물
    try:
        from engine.data.provider_crypto import _build_futures_exchange
        ex = _build_futures_exchange("binance")
        markets = ex.load_markets()
        # 인덱스 토큰 제외 (BTCDOM, DEFIUSDT 등 거래 불가)
        excluded_keywords = {"DOM", "DEFI"}
        for s, m in markets.items():
            if m.get("swap") and m.get("quote") == "USDT" and m.get("active"):
                base = s.replace(":USDT", "").replace("/USDT", "")
                if not any(kw in base for kw in excluded_keywords):
                    syms.add(s.replace(":USDT", ""))
    except Exception:
        pass
    # fallback: 최소 기본 종목
    if not syms:
        syms = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
        try:
            from engine.strategy.alt_momentum import VALIDATED_SYMBOLS
            syms.update(VALIDATED_SYMBOLS)
        except Exception:
            pass
    # 거래이력 종목 추가
    alt_data = read_alt_state()
    for t in alt_data.get("trade_log", []):
        if t.get("symbol"): syms.add(t["symbol"])
    return sorted(syms)


def get_history() -> dict:
    """통합 매매 히스토리."""
    trades = []

    btc_state = read_bot_state()
    for t in btc_state.get("trade_log", []):
        trades.append({
            "bot": "BTC_선물_봇",
            "symbol": t.get("symbol", "BTC/USDT"),
            "side": t.get("side", ""),
            "entry": t.get("entry_price", 0),
            "exit": t.get("exit_price", 0),
            "pnl": t.get("pnl_pct", 0),
            "bars": t.get("bars_held", 0),
            "reason": t.get("reason", ""),
            "entry_time": t.get("entry_time", ""),
            "exit_time": t.get("exit_time", ""),
            "entry_reason": t.get("extra", {}).get("reason", "") if isinstance(t.get("extra"), dict) else "",
        })

    alt_data = read_alt_state()
    for t in alt_data.get("trade_log", []):
        trades.append({
            "bot": "알트_데일리_봇",
            "symbol": t.get("symbol", ""),
            "side": t.get("side", "LONG"),
            "entry": t.get("entry_price", 0),
            "exit": t.get("exit_price", 0),
            "pnl": t.get("pnl_pct", 0),
            "bars": t.get("bars_held", 0),
            "reason": t.get("reason", ""),
            "entry_time": t.get("entry_time", ""),
            "exit_time": t.get("exit_time", ""),
            "entry_reason": t.get("extra", {}).get("reason", "") if isinstance(t.get("extra"), dict) else "",
        })

    trades.sort(key=lambda x: x.get("exit_time", ""), reverse=True)

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

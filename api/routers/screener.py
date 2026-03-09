"""Coin screener — technical analysis scoring for all watched symbols."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/screener", tags=["screener"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CoinAnalysis(BaseModel):
    symbol: str
    sector: str
    price: float
    rsi: float
    bb_pct: float
    ema50_above: bool
    ema200_above: bool
    ret_5d: float
    ret_20d: float
    bullish_candles: int
    vol_ratio: float
    long_score: int
    short_score: int
    funding_rate: float | None = None
    atr_pct: float
    macd_hist: float
    summary: str


class ScreenerResponse(BaseModel):
    coins: list[CoinAnalysis]
    regime: str
    exposure: float
    scanned_at: str


# ---------------------------------------------------------------------------
# Sector map (shared with regime/sector.py)
# ---------------------------------------------------------------------------

SECTOR_MAP: dict[str, list[str]] = {
    "L1": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "AVAX/USDT", "NEAR/USDT", "APT/USDT", "SUI/USDT"],
    "L2": ["ARB/USDT", "OP/USDT", "MATIC/USDT"],
    "DeFi": ["LINK/USDT", "UNI/USDT", "AAVE/USDT", "SNX/USDT"],
    "AI": ["FET/USDT", "RNDR/USDT"],
    "Meme": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "FLOKI/USDT"],
    "Gaming": ["AXS/USDT", "SAND/USDT", "MANA/USDT", "GALA/USDT", "IMX/USDT"],
}

SYMBOL_SECTOR = {sym: sect for sect, syms in SECTOR_MAP.items() for sym in syms}
ALL_SYMBOLS = [sym for syms in SECTOR_MAP.values() for sym in syms]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _calc_macd(series: pd.Series) -> pd.Series:
    ema12 = series.ewm(span=12).mean()
    ema26 = series.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    return macd_line - signal_line  # histogram


def _analyze_coin(df: pd.DataFrame, symbol: str, funding_rate: float | None = None) -> CoinAnalysis | None:
    """Analyze a single coin and return scoring."""
    if len(df) < 30:
        return None

    close = df["close"]
    volume = df["volume"]
    c = float(close.iloc[-1])

    # RSI
    rsi = float(_calc_rsi(close, 14).iloc[-1])

    # Bollinger Bands %
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_lower = float((sma20 - 2 * std20).iloc[-1])
    bb_upper = float((sma20 + 2 * std20).iloc[-1])
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper != bb_lower else 50

    # EMAs
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema200 = float(close.ewm(span=200).mean().iloc[-1]) if len(df) >= 200 else ema50

    # Returns
    ret_5d = (c / float(close.iloc[-6]) - 1) * 100 if len(df) > 6 else 0
    ret_20d = (c / float(close.iloc[-21]) - 1) * 100 if len(df) > 21 else 0

    # Bullish candles (last 3)
    bullish_cnt = sum(1 for i in range(-3, 0) if df["close"].iloc[i] > df["open"].iloc[i])

    # Volume ratio
    baseline = float(volume.iloc[-23:-3].mean()) if len(df) > 23 else float(volume.mean())
    vol_ratio = float(volume.iloc[-3:].mean() / baseline) if baseline > 0 else 0

    # ATR %
    high_low = df["high"] - df["low"]
    atr14 = float(high_low.rolling(14).mean().iloc[-1])
    atr_pct = atr14 / c * 100

    # MACD histogram
    macd_hist = float(_calc_macd(close).iloc[-1])

    # --- LONG score (0~10) ---
    long_score = 0
    if rsi < 30:
        long_score += 3
    elif rsi < 40:
        long_score += 2
    elif rsi < 50:
        long_score += 1
    if bb_pct < 15:
        long_score += 3
    elif bb_pct < 30:
        long_score += 2
    elif bb_pct < 45:
        long_score += 1
    if c > ema50:
        long_score += 1
    if bullish_cnt >= 2:
        long_score += 1
    if vol_ratio > 1.5:
        long_score += 1
    if ret_5d > 0 and ret_5d < 15:
        long_score += 1

    # --- SHORT score (0~10) ---
    short_score = 0
    if rsi > 70:
        short_score += 3
    elif rsi > 60:
        short_score += 2
    elif rsi > 50:
        short_score += 1
    if bb_pct > 85:
        short_score += 3
    elif bb_pct > 70:
        short_score += 2
    elif bb_pct > 55:
        short_score += 1
    if c < ema50:
        short_score += 1
    if bullish_cnt <= 1:
        short_score += 1
    if vol_ratio > 1.5:
        short_score += 1
    if ret_5d < 0:
        short_score += 1

    # Summary
    signals = []
    if rsi < 30:
        signals.append("극과매도")
    elif rsi < 40:
        signals.append("과매도")
    elif rsi > 70:
        signals.append("극과매수")
    elif rsi > 60:
        signals.append("과매수")

    if bb_pct < 20:
        signals.append("BB하단")
    elif bb_pct > 80:
        signals.append("BB상단")

    if ret_5d > 10:
        signals.append(f"5일 급등 {ret_5d:+.1f}%")
    elif ret_5d < -10:
        signals.append(f"5일 급락 {ret_5d:+.1f}%")

    if vol_ratio > 2:
        signals.append(f"거래량 {vol_ratio:.1f}x")

    if macd_hist > 0 and float(_calc_macd(close).iloc[-2]) < 0:
        signals.append("MACD 골든")
    elif macd_hist < 0 and float(_calc_macd(close).iloc[-2]) > 0:
        signals.append("MACD 데드")

    summary = " | ".join(signals) if signals else "특이사항 없음"

    return CoinAnalysis(
        symbol=symbol,
        sector=SYMBOL_SECTOR.get(symbol, "기타"),
        price=round(c, 6),
        rsi=round(rsi, 1),
        bb_pct=round(bb_pct, 1),
        ema50_above=c > ema50,
        ema200_above=c > ema200,
        ret_5d=round(ret_5d, 2),
        ret_20d=round(ret_20d, 2),
        bullish_candles=bullish_cnt,
        vol_ratio=round(vol_ratio, 2),
        long_score=min(long_score, 10),
        short_score=min(short_score, 10),
        funding_rate=round(funding_rate, 6) if funding_rate is not None else None,
        atr_pct=round(atr_pct, 2),
        macd_hist=round(macd_hist, 6),
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/scan", response_model=ScreenerResponse)
def scan_all(
    symbols: str | None = Query(None, description="Comma-separated symbols (e.g. BTC/USDT,ETH/USDT)"),
    sort_by: str = Query("long_score", description="Sort field: long_score, short_score, rsi, ret_5d"),
    sort_dir: str = Query("desc", description="Sort direction: asc or desc"),
) -> ScreenerResponse:
    """Scan coins and return technical analysis scores."""
    from engine.data.provider_crypto import CryptoProvider
    from engine.regime.crypto import CryptoRegimeEngine

    # Current regime
    try:
        regime_state = CryptoRegimeEngine().compute()
        regime_name = regime_state.regime
        exposure = regime_state.exposure
    except Exception:
        regime_name = "SELECTIVE"
        exposure = 0.3

    # Funding rates (best effort)
    funding_rates: dict[str, float] = {}
    try:
        from engine.strategy.funding import fetch_funding_rates
        target_list = symbols.split(",") if symbols else ALL_SYMBOLS
        funding_rates = fetch_funding_rates(target_list)
    except Exception:
        pass

    provider = CryptoProvider()
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    target_list = symbols.split(",") if symbols else ALL_SYMBOLS

    coins: list[CoinAnalysis] = []
    for sym in target_list:
        try:
            start_d = (pd.Timestamp(end) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")
            df = provider.fetch_ohlcv(sym.strip(), start_d, end, "1d")
            analysis = _analyze_coin(df, sym.strip(), funding_rates.get(sym.strip()))
            if analysis:
                coins.append(analysis)
        except Exception as e:
            logger.warning("Screener error for %s: %s", sym, e)

    # Sort
    reverse = sort_dir.lower() != "asc"
    coins.sort(key=lambda x: getattr(x, sort_by, 0), reverse=reverse)

    return ScreenerResponse(
        coins=coins,
        regime=regime_name,
        exposure=exposure,
        scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


@router.get("/coin/{symbol}", response_model=CoinAnalysis)
def analyze_coin(symbol: str) -> CoinAnalysis:
    """Analyze a single coin by symbol (e.g. BTCUSDT → BTC/USDT)."""
    from engine.data.provider_crypto import CryptoProvider

    # Normalize symbol
    sym = symbol.upper()
    if "/" not in sym and sym.endswith("USDT"):
        sym = sym[:-4] + "/USDT"

    # Funding rate
    fr = None
    try:
        from engine.strategy.funding import fetch_funding_rate
        fr = fetch_funding_rate(sym)
    except Exception:
        pass

    provider = CryptoProvider()
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    start_d = (pd.Timestamp(end) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")
    df = provider.fetch_ohlcv(sym, start_d, end, "1d")

    result = _analyze_coin(df, sym, fr)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(404, f"Insufficient data for {sym}")
    return result

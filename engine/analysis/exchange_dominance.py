"""Exchange dominance analysis for a single coin.

Provides:
- top-3 exchange volume ratios
- dominant exchange
- Upbit trading reference prices based on dominant exchange fair value
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExchangeQuote:
    exchange: str
    symbol: str
    last: float
    quote_volume: float
    quote_volume_usd: float


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _load_ccxt_exchange(name: str):
    import ccxt

    if name == "bybit":
        return ccxt.bybit()
    if name == "okx":
        return ccxt.okx()
    if name == "bitget":
        return ccxt.bitget()
    if name == "gateio":
        return ccxt.gateio()
    return ccxt.binance()


def fetch_exchange_ohlcv(
    exchange_name: str,
    base: str,
    interval: str = "5m",
    count: int = 200,
):
    """Fetch OHLCV for BASE/USDT from a given exchange via ccxt."""
    import pandas as pd

    tf_map = {
        "5m": "5m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
    }
    ex = _load_ccxt_exchange(exchange_name)
    symbol = f"{base.upper()}/USDT"
    rows = ex.fetch_ohlcv(symbol, timeframe=tf_map.get(interval, interval), limit=count)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def _fetch_usdt_quote(exchange_name: str, base: str) -> ExchangeQuote | None:
    """Fetch one exchange quote for BASE/USDT."""
    try:
        ex = _load_ccxt_exchange(exchange_name)
        symbol = f"{base}/USDT"
        t = ex.fetch_ticker(symbol)
        last = _safe_float(t.get("last"))
        qv = _safe_float(t.get("quoteVolume"))
        if last <= 0 or qv <= 0:
            return None
        return ExchangeQuote(
            exchange=exchange_name,
            symbol=symbol,
            last=last,
            quote_volume=qv,
            quote_volume_usd=qv,  # USDT quote volume ~ USD
        )
    except Exception as e:
        logger.debug("dominance quote failed: %s %s", exchange_name, e)
        return None


def _fetch_upbit_quote(base: str, usdkrw: float) -> ExchangeQuote | None:
    import pyupbit

    symbol = f"KRW-{base}"
    try:
        # price
        p = pyupbit.get_current_price(symbol)
        last = _safe_float(p)
        if last <= 0:
            return None
        # 24h trade amount from ticker endpoint
        import requests

        resp = requests.get("https://api.upbit.com/v1/ticker", params={"markets": symbol}, timeout=10)
        qv = 0.0
        if resp.status_code == 200 and resp.json():
            qv = _safe_float(resp.json()[0].get("acc_trade_price_24h"))
        if qv <= 0:
            return None
        qv_usd = qv / usdkrw if usdkrw > 0 else 0.0
        return ExchangeQuote(
            exchange="upbit",
            symbol=symbol,
            last=last,
            quote_volume=qv,
            quote_volume_usd=qv_usd,
        )
    except Exception as e:
        logger.debug("dominance quote failed: upbit %s", e)
        return None


def _ratio_rows(rows: list[ExchangeQuote]) -> list[dict]:
    total = sum(r.quote_volume_usd for r in rows) or 1.0
    out = []
    for r in rows:
        out.append(
            {
                "exchange": r.exchange,
                "symbol": r.symbol,
                "last": round(r.last, 8),
                "quote_volume_24h": round(r.quote_volume, 2),
                "quote_volume_24h_usd": round(r.quote_volume_usd, 2),
                "ratio_pct": round(r.quote_volume_usd / total * 100.0, 2),
            }
        )
    out.sort(key=lambda x: x["quote_volume_24h_usd"], reverse=True)
    return out


def analyze_exchange_dominance(
    base: str,
    usdkrw: float = 1350.0,
    fee_buffer_bps: float = 20.0,
) -> dict:
    """Analyze exchange dominance and derive Upbit trading reference prices.

    Args:
        base: coin ticker like "BTC", "ETH".
        usdkrw: FX conversion for fair KRW estimate.
        fee_buffer_bps: buffer around fair price (bps) for conservative buy/sell refs.
    """
    base = base.upper()
    exchange_candidates = ["binance", "bybit", "okx", "bitget", "gateio"]
    usdt_quotes: list[ExchangeQuote] = []
    for ex in exchange_candidates:
        q = _fetch_usdt_quote(ex, base)
        if q is not None:
            usdt_quotes.append(q)

    upbit_q = _fetch_upbit_quote(base, usdkrw=usdkrw)
    all_rows = list(usdt_quotes)
    if upbit_q is not None:
        all_rows.append(upbit_q)

    if not all_rows:
        return {"error": "no_market_data", "base": base}

    ranked = _ratio_rows(all_rows)
    top3 = ranked[:3]
    dominant = top3[0] if top3 else ranked[0]
    # Reference exchange for comparison chart:
    # if dominant is upbit, pick next non-upbit exchange.
    ref = dominant
    if str(dominant.get("exchange", "")).lower() == "upbit":
        for r in ranked:
            if str(r.get("exchange", "")).lower() != "upbit":
                ref = r
                break

    # Upbit trading reference:
    # fair_krw is dominant USDT market converted to KRW (or dominant itself if KRW market)
    dominant_last = float(dominant["last"])
    if dominant["symbol"].endswith("/USDT"):
        fair_krw = dominant_last * usdkrw
    else:
        fair_krw = dominant_last

    upbit_last = float(upbit_q.last) if upbit_q else 0.0
    premium_pct = (upbit_last / fair_krw - 1.0) * 100.0 if fair_krw > 0 and upbit_last > 0 else 0.0

    buffer = fee_buffer_bps / 10000.0
    buy_ref = fair_krw * (1.0 - buffer)
    sell_ref = fair_krw * (1.0 + buffer)
    gap_pct = (upbit_last / fair_krw - 1.0) * 100.0 if upbit_last > 0 and fair_krw > 0 else 0.0

    return {
        "base": base,
        "top3_exchanges": top3,
        "dominant_exchange": dominant,
        "reference_exchange": ref,
        "upbit_trading_refs": {
            "upbit_last_krw": round(upbit_last, 2) if upbit_last > 0 else None,
            "fair_krw_from_dominant": round(fair_krw, 2),
            "buy_ref_krw": round(buy_ref, 2),
            "sell_ref_krw": round(sell_ref, 2),
            "gap_vs_fair_pct": round(gap_pct, 3),
            "kimchi_premium_pct": round(premium_pct, 3),
            "usdkrw": usdkrw,
            "fee_buffer_bps": fee_buffer_bps,
        },
        "all_exchanges_ranked": ranked,
    }

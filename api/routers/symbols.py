"""Symbol search API — lazy-loaded in-memory cache of KRX, NASDAQ, NYSE, and crypto symbols."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/symbols", tags=["symbols"])

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache: list[dict[str, str]] = []
_cache_lock = threading.Lock()
_cache_loaded = False


def _load_kr() -> list[dict[str, str]]:
    """Load KRX listings via FinanceDataReader."""
    try:
        import FinanceDataReader as fdr

        df = fdr.StockListing("KRX")
        results: list[dict[str, str]] = []
        for _, row in df.iterrows():
            code = str(row.get("Code", row.get("Symbol", ""))).strip()
            name = str(row.get("Name", "")).strip()
            if code and name:
                results.append({"symbol": code, "name": name, "market": "kr_stock"})
        logger.info("Loaded %d KRX symbols", len(results))
        return results
    except Exception as e:
        logger.warning("Failed to load KRX symbols: %s", e)
        return []


def _load_us(exchange: str) -> list[dict[str, str]]:
    """Load US stock listings (NASDAQ or NYSE) via FinanceDataReader."""
    try:
        import FinanceDataReader as fdr

        df = fdr.StockListing(exchange)
        results: list[dict[str, str]] = []
        for _, row in df.iterrows():
            sym = str(row.get("Symbol", row.get("Code", ""))).strip()
            name = str(row.get("Name", "")).strip()
            if sym and name:
                results.append({"symbol": sym, "name": name, "market": "us_stock"})
        logger.info("Loaded %d %s symbols", len(results), exchange)
        return results
    except Exception as e:
        logger.warning("Failed to load %s symbols: %s", exchange, e)
        return []


def _load_crypto() -> list[dict[str, str]]:
    """Load crypto trading pairs via ccxt (Binance)."""
    try:
        import ccxt

        exchange = ccxt.binance()
        exchange.load_markets()
        results: list[dict[str, str]] = []
        for sym in exchange.symbols:
            results.append({"symbol": sym, "name": sym, "market": "crypto_spot"})
        logger.info("Loaded %d crypto symbols", len(results))
        return results
    except Exception as e:
        logger.warning("Failed to load crypto symbols: %s", e)
        return []


def _ensure_cache() -> None:
    """Populate the cache on first access (thread-safe)."""
    global _cache_loaded
    if _cache_loaded:
        return
    with _cache_lock:
        if _cache_loaded:
            return
        logger.info("Loading symbol cache (first request)...")
        _cache.extend(_load_kr())
        _cache.extend(_load_us("NASDAQ"))
        _cache.extend(_load_us("NYSE"))
        _cache.extend(_load_crypto())
        _cache_loaded = True
        logger.info("Symbol cache ready: %d total symbols", len(_cache))


# ---------------------------------------------------------------------------
# Public helpers (used by other routers, e.g. backtests/scan)
# ---------------------------------------------------------------------------


def get_symbols_by_market(market: str) -> list[dict[str, str]]:
    """Return all cached symbols for a given market."""
    _ensure_cache()
    return [item for item in _cache if item["market"] == market]


def get_symbol_name(symbol: str, market: str | None = None) -> str:
    """Look up display name for a symbol. Returns symbol itself if not found."""
    _ensure_cache()
    for item in _cache:
        if item["symbol"] == symbol and (market is None or item["market"] == market):
            return item["name"]
    return symbol


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class SymbolResult(BaseModel):
    symbol: str
    name: str
    market: str


class SymbolSearchResponse(BaseModel):
    results: list[SymbolResult]


@router.get("/search", response_model=SymbolSearchResponse)
def search_symbols(
    q: str = "",
    market: str | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    _ensure_cache()

    if not q:
        return {"results": []}

    query = q.lower()
    matches: list[dict[str, str]] = []

    for item in _cache:
        if market and item["market"] != market:
            continue
        if query in item["symbol"].lower() or query in item["name"].lower():
            matches.append(item)
            if len(matches) >= limit:
                break

    return {"results": matches}

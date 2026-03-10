"""CCXT-based data provider for crypto spot and futures markets."""

import json
import threading
import time
from functools import lru_cache
from pathlib import Path

import ccxt
import pandas as pd

from engine.data.provider_base import DataProvider

_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
}

_DEFAULT_EXCHANGES = ["binance", "bybit", "okx", "upbit"]
_SYMBOL_CACHE_DIR = Path("config/exchange_symbol_cache")
_SYMBOL_CACHE_TTL_SEC = 60 * 60 * 12
_PRELOAD_STARTED = False

class CryptoProvider(DataProvider):
    """Data provider for crypto markets using ccxt."""

    def __init__(self, exchange: str = "binance") -> None:
        self.exchange_name = exchange
        self._exchange: ccxt.Exchange = _build_exchange(exchange)

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        ccxt_timeframe = _TIMEFRAME_MAP.get(timeframe, timeframe)

        since_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)

        all_rows: list[list] = []
        while True:
            rows = self._exchange.fetch_ohlcv(
                symbol,
                timeframe=ccxt_timeframe,
                since=since_ms,
                limit=1000,
            )
            if not rows:
                break
            all_rows.extend(rows)
            last_ts = rows[-1][0]
            if last_ts >= end_ms:
                break
            since_ms = last_ts + 1

        df = pd.DataFrame(
            all_rows,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df

@lru_cache(maxsize=16)
def _build_exchange(exchange: str) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange)
    return exchange_class()

def get_supported_crypto_exchanges() -> list[str]:
    exchanges = [name for name in _DEFAULT_EXCHANGES if hasattr(ccxt, name)]
    return sorted(exchanges)

def load_exchange_symbols(exchange: str) -> list[str]:
    cached = _load_cached_symbols(exchange)
    if cached is not None:
        return cached
    return _refresh_exchange_symbols(exchange)

def warm_exchange_symbol_caches(exchanges: list[str] | None = None) -> None:
    global _PRELOAD_STARTED
    if _PRELOAD_STARTED:
        return
    _PRELOAD_STARTED = True
    selected = exchanges or get_supported_crypto_exchanges()

    def _run() -> None:
        for exchange in selected:
            try:
                load_exchange_symbols(exchange)
            except Exception:
                continue

    threading.Thread(target=_run, daemon=True).start()

def _refresh_exchange_symbols(exchange: str) -> list[str]:
    client = _build_exchange(exchange)
    markets = client.load_markets()
    symbols = sorted(markets.keys())
    _write_symbol_cache(exchange, symbols)
    return symbols

def _load_cached_symbols(exchange: str) -> list[str] | None:
    path = _symbol_cache_path(exchange)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        ts = float(data.get("cached_at", 0))
        if time.time() - ts > _SYMBOL_CACHE_TTL_SEC:
            return None
        symbols = data.get("symbols", [])
        if isinstance(symbols, list) and symbols:
            return [str(item) for item in symbols]
    except Exception:
        return None
    return None

def _write_symbol_cache(exchange: str, symbols: list[str]) -> None:
    path = _symbol_cache_path(exchange)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cached_at": time.time(), "symbols": symbols}))

def _symbol_cache_path(exchange: str) -> Path:
    return _SYMBOL_CACHE_DIR / f"{exchange}.json"

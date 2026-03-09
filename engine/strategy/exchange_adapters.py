"""Exchange adapter layer for scanner/analysis portability.

This module provides a small common interface so analysis/scanner code
can switch between Upbit and Binance without hardcoding exchange logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


def _to_df(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def normalize_interval(exchange: str, interval: str) -> str:
    """Normalize timeframe labels for each exchange client."""
    mapping = {
        "upbit": {
            "1m": "minute1",
            "3m": "minute3",
            "5m": "minute5",
            "15m": "minute15",
            "30m": "minute30",
            "1h": "minute60",
            "4h": "minute240",
            "1d": "day",
            "1w": "week",
        },
        "binance": {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
            "1w": "1w",
        },
    }
    return mapping.get(exchange, {}).get(interval, interval)


@dataclass
class ExchangeAdapter:
    exchange: str

    def fetch_ohlcv(self, symbol: str, interval: str = "5m", count: int = 200) -> pd.DataFrame | None:
        raise NotImplementedError

    def get_active_symbols(self, max_symbols: int = 30) -> list[str]:
        raise NotImplementedError

    def display_symbol(self, symbol: str) -> str:
        return symbol


class UpbitAdapter(ExchangeAdapter):
    def __init__(self) -> None:
        super().__init__(exchange="upbit")

    def fetch_ohlcv(self, symbol: str, interval: str = "5m", count: int = 200) -> pd.DataFrame | None:
        import pyupbit

        upbit_interval = normalize_interval("upbit", interval)
        try:
            df = pyupbit.get_ohlcv(symbol, interval=upbit_interval, count=count)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.warning("Upbit fetch failed: %s %s %s", symbol, interval, e)
            return None

    def get_active_symbols(self, max_symbols: int = 30) -> list[str]:
        import requests
        import pyupbit

        try:
            tickers = pyupbit.get_tickers(fiat="KRW") or []
            if not tickers:
                return []
            active: list[tuple[str, float]] = []
            url = "https://api.upbit.com/v1/ticker"
            for i in range(0, len(tickers), 100):
                chunk = tickers[i:i + 100]
                resp = requests.get(url, params={"markets": ",".join(chunk)}, timeout=10)
                if resp.status_code != 200:
                    continue
                for item in resp.json():
                    active.append((item["market"], float(item.get("acc_trade_price_24h", 0))))
            active.sort(key=lambda x: x[1], reverse=True)
            return [s for s, _ in active[:max_symbols]]
        except Exception as e:
            logger.warning("Upbit symbol list failed: %s", e)
            return []

    def display_symbol(self, symbol: str) -> str:
        return symbol.replace("KRW-", "")


class BinanceAdapter(ExchangeAdapter):
    def __init__(self, market_type: str = "spot") -> None:
        super().__init__(exchange="binance")
        import ccxt

        options = {"options": {"defaultType": "future"}} if market_type == "future" else {}
        self._ex = ccxt.binance(options)

    def fetch_ohlcv(self, symbol: str, interval: str = "5m", count: int = 200) -> pd.DataFrame | None:
        tf = normalize_interval("binance", interval)
        try:
            rows = self._ex.fetch_ohlcv(symbol, timeframe=tf, limit=count)
            if not rows:
                return None
            return _to_df(rows)
        except Exception as e:
            logger.warning("Binance fetch failed: %s %s %s", symbol, interval, e)
            return None

    def get_active_symbols(self, max_symbols: int = 30) -> list[str]:
        try:
            tickers = self._ex.fetch_tickers()
            pairs: list[tuple[str, float]] = []
            for sym, t in tickers.items():
                if not sym.endswith("/USDT"):
                    continue
                qv = t.get("quoteVolume") or 0
                pairs.append((sym, float(qv)))
            pairs.sort(key=lambda x: x[1], reverse=True)
            return [s for s, _ in pairs[:max_symbols]]
        except Exception as e:
            logger.warning("Binance symbol list failed: %s", e)
            return []

    def display_symbol(self, symbol: str) -> str:
        return symbol.replace("/USDT", "")


def get_exchange_adapter(name: str) -> ExchangeAdapter:
    v = (name or "upbit").lower()
    if v == "binance":
        return BinanceAdapter()
    return UpbitAdapter()


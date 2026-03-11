"""Orderbook depth snapshot collector using ccxt REST API."""

from __future__ import annotations

import logging
from pathlib import Path

import ccxt
import pandas as pd

from engine.data.depth_cache import DepthCache

logger = logging.getLogger(__name__)


class OrderbookDepthCollector:
    """Collect orderbook depth snapshots via ccxt ``fetch_order_book``.

    Designed for periodic cron execution (e.g. every 1 minute) rather than
    continuous WebSocket streaming -- simpler and sufficient for building
    statistical depth profiles used by :class:`VolumeAdjustedSlippage`.
    """

    def __init__(
        self,
        exchange: str = "binance",
        cache_dir: Path = Path(".cache/depth"),
    ) -> None:
        self._exchange = getattr(ccxt, exchange)()
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._depth_cache = DepthCache(cache_dir=cache_dir)

    def collect_snapshot(self, symbol: str, limit: int = 20) -> dict:
        """Fetch a single orderbook snapshot and return stats dict.

        Args:
            symbol: Trading pair (e.g. ``"BTC/USDT"``).
            limit: Number of orderbook levels to fetch (top N).

        Returns:
            Dict with keys: symbol, timestamp, bid_depth_usd,
            ask_depth_usd, spread_pct, best_bid, best_ask, levels.
        """
        book = self._exchange.fetch_order_book(symbol, limit=limit)

        bid_depth_usd = sum(p * a for p, a in book["bids"])
        ask_depth_usd = sum(p * a for p, a in book["asks"])
        best_bid = book["bids"][0][0] if book["bids"] else 0.0
        best_ask = book["asks"][0][0] if book["asks"] else 0.0
        spread_pct = (best_ask - best_bid) / best_bid if best_bid > 0 else 0.0

        return {
            "symbol": symbol,
            "timestamp": pd.Timestamp.now(tz="UTC"),
            "bid_depth_usd": bid_depth_usd,
            "ask_depth_usd": ask_depth_usd,
            "spread_pct": spread_pct,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "levels": limit,
        }

    def collect_top_symbols(self, n: int = 50) -> list[dict]:
        """Fetch depth snapshots for the top *n* symbols by 24h quote volume.

        Uses ``fetch_tickers()`` to rank symbols, then collects a snapshot
        for each.  Symbols that fail are silently skipped.
        """
        self._exchange.load_markets()
        tickers = self._exchange.fetch_tickers()

        sorted_symbols = sorted(
            tickers.items(),
            key=lambda x: x[1].get("quoteVolume", 0) or 0,
            reverse=True,
        )[:n]

        snapshots: list[dict] = []
        for symbol, _ in sorted_symbols:
            try:
                snap = self.collect_snapshot(symbol)
                snapshots.append(snap)
            except Exception:
                logger.debug("Skipped %s during depth collection", symbol, exc_info=True)
                continue

        return snapshots

    def save_to_cache(self, snapshots: list[dict]) -> None:
        """Persist collected snapshots via :class:`DepthCache`."""
        self._depth_cache.save_snapshot(snapshots)

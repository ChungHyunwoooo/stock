"""Parquet-based cache for orderbook depth statistics with TTL expiration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class DepthCache:
    """File-based cache storing orderbook depth statistics as Parquet.

    Follows the same pattern as ohlcv_cache.ParquetCache but specialised
    for depth snapshots (symbol-level aggregated statistics).
    """

    def __init__(
        self,
        cache_dir: Path = Path(".cache/depth"),
        ttl_days: int = 7,
    ) -> None:
        self._cache_dir = cache_dir
        self._ttl = timedelta(days=ttl_days)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stats(self, symbol: str) -> dict | None:
        """Return aggregated depth stats for *symbol*, or ``None``.

        Returns dict with keys ``avg_spread_pct`` and ``avg_depth_usd_10``
        when valid cached data exists.  Returns ``None`` when no data is
        found or the cached file has exceeded its TTL.
        """
        path = self._snapshot_path()
        if not path.exists():
            return None

        # TTL check
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(tz=timezone.utc) - mtime > self._ttl:
            logger.warning("Depth cache expired for %s (TTL=%s)", symbol, self._ttl)
            return None

        df = pd.read_parquet(path)
        sym_df = df[df["symbol"] == symbol]
        if sym_df.empty:
            return None

        return self._aggregate_stats(sym_df)

    def save_snapshot(self, records: list[dict]) -> None:
        """Persist a list of depth snapshot dicts to Parquet.

        Each record should contain at least: ``symbol``, ``timestamp``,
        ``bid_depth_usd``, ``ask_depth_usd``, ``spread_pct``.
        """
        if not records:
            return
        df = pd.DataFrame(records)
        path = self._snapshot_path()

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)

        df.to_parquet(path, index=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_path(self) -> Path:
        return self._cache_dir / "depth_snapshots.parquet"

    @staticmethod
    def _aggregate_stats(df: pd.DataFrame) -> dict:
        """Compute average spread and depth from snapshot rows."""
        avg_spread = float(df["spread_pct"].mean())
        avg_depth = float((df["bid_depth_usd"] + df["ask_depth_usd"]).mean())
        return {
            "avg_spread_pct": avg_spread,
            "avg_depth_usd_10": avg_depth,
        }

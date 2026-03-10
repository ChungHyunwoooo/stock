"""Parquet-based cache for market data with TTL expiration."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

class ParquetCache:
    """File-based cache storing DataFrames as parquet files with TTL expiration."""

    def __init__(
        self,
        cache_dir: Path = Path(".cache/market_data"),
        ttl_hours: int = 24,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, symbol: str, start: str, end: str, timeframe: str) -> Path:
        filename = f"{symbol}_{timeframe}_{start}_{end}.parquet"
        return self.cache_dir / filename

    def get(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
    ) -> pd.DataFrame | None:
        path = self._key(symbol, start, end, timeframe)
        if not path.exists():
            return None

        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(tz=timezone.utc) - mtime > self.ttl:
            path.unlink(missing_ok=True)
            return None

        return pd.read_parquet(path)

    def put(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> None:
        path = self._key(symbol, start, end, timeframe)
        df.to_parquet(path)

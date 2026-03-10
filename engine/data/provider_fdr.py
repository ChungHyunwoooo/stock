"""FinanceDataReader-based data provider for KR/US stocks."""

import pandas as pd
import FinanceDataReader as fdr

from engine.data.provider_base import DataProvider

class FDRProvider(DataProvider):
    """Data provider for Korean and US stock markets using FinanceDataReader."""

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        df = fdr.DataReader(symbol, start, end)

        # Normalize column names to lowercase
        df.columns = [c.lower() for c in df.columns]

        # Keep only required OHLCV columns
        required = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in required if c in df.columns]]

        # Ensure DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        return df

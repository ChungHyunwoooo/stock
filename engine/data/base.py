"""Abstract data provider base and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from engine.schema import MarketType


class DataProvider(ABC):
    """Abstract base class for all market data providers."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a symbol.

        Returns a DataFrame with columns: open, high, low, close, volume
        and a DatetimeIndex.
        """


def get_provider(market_type: MarketType, **kwargs) -> DataProvider:
    """Factory function returning the appropriate DataProvider for a market type."""
    from engine.data.provider_fdr import FDRProvider
    from engine.data.provider_crypto import CryptoProvider

    if market_type in (MarketType.kr_stock, MarketType.us_stock):
        return FDRProvider()
    if market_type in (MarketType.crypto_spot, MarketType.crypto_futures):
        exchange = kwargs.get("exchange", "binance")
        if exchange == "upbit":
            from engine.data.provider_upbit import UpbitProvider
            return UpbitProvider(realtime=kwargs.get("realtime", False))
        return CryptoProvider(exchange=exchange)
    raise ValueError(f"Unsupported market type: {market_type}")

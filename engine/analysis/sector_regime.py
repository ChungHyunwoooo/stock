"""Crypto sector ranker — ranks sectors by relative strength."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.data.provider_crypto import CryptoProvider

# Sector → representative symbols mapping
SECTOR_MAP: dict[str, list[str]] = {
    "L1": ["ETH/USDT", "SOL/USDT", "ADA/USDT", "AVAX/USDT", "NEAR/USDT"],
    "L2": ["MATIC/USDT", "ARB/USDT", "OP/USDT"],
    "DeFi": ["UNI/USDT", "AAVE/USDT", "LINK/USDT", "MKR/USDT", "SNX/USDT"],
    "AI": ["FET/USDT", "RNDR/USDT", "AGIX/USDT", "OCEAN/USDT"],
    "Meme": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "FLOKI/USDT"],
    "Gaming": ["AXS/USDT", "SAND/USDT", "MANA/USDT", "GALA/USDT", "IMX/USDT"],
}

@dataclass
class SymbolStrength:
    """Single symbol's relative strength."""
    symbol: str
    return_pct: float
    sector: str

@dataclass
class SectorRank:
    """Sector ranking result."""
    sector: str
    avg_return_pct: float
    rank: int
    symbols: list[SymbolStrength]

class CryptoSectorRanker:
    """Ranks crypto sectors by average return over a period."""

    def __init__(self, sector_map: dict[str, list[str]] | None = None) -> None:
        self._sector_map = sector_map or SECTOR_MAP
        self._provider = CryptoProvider()

    def _fetch_return(self, symbol: str, start: str, end: str) -> float | None:
        """Fetch return for a symbol over the period."""
        try:
            df = self._provider.fetch_ohlcv(symbol, start, end, "1d")
            if len(df) < 2:
                return None
            first_close = float(df["close"].iloc[0])
            last_close = float(df["close"].iloc[-1])
            if first_close == 0:
                return None
            return ((last_close / first_close) - 1.0) * 100
        except Exception:
            return None

    def rank_sectors(self, date: str | None = None, period: int = 20) -> list[SectorRank]:
        """Rank sectors by average return over the last N days.

        Args:
            date: End date (default: today)
            period: Lookback period in days

        Returns:
            List of SectorRank sorted by avg_return_pct descending
        """
        if date is None:
            end = pd.Timestamp.now().strftime("%Y-%m-%d")
        else:
            end = date
        start = (pd.Timestamp(end) - pd.Timedelta(days=period + 5)).strftime("%Y-%m-%d")

        sector_results: list[SectorRank] = []

        for sector_name, symbols in self._sector_map.items():
            symbol_strengths: list[SymbolStrength] = []

            for sym in symbols:
                ret = self._fetch_return(sym, start, end)
                if ret is not None:
                    symbol_strengths.append(SymbolStrength(
                        symbol=sym,
                        return_pct=round(ret, 2),
                        sector=sector_name,
                    ))

            if symbol_strengths:
                avg_ret = sum(s.return_pct for s in symbol_strengths) / len(symbol_strengths)
            else:
                avg_ret = 0.0

            # Sort symbols within sector by return desc
            symbol_strengths.sort(key=lambda s: s.return_pct, reverse=True)

            sector_results.append(SectorRank(
                sector=sector_name,
                avg_return_pct=round(avg_ret, 2),
                rank=0,  # will be set after sorting
                symbols=symbol_strengths,
            ))

        # Sort by avg return and assign rank
        sector_results.sort(key=lambda s: s.avg_return_pct, reverse=True)
        for i, sr in enumerate(sector_results):
            sr.rank = i + 1

        return sector_results

    def get_top_symbols(
        self,
        date: str | None = None,
        period: int = 20,
        top_n_sectors: int = 2,
        top_n_per_sector: int = 3,
    ) -> list[SymbolStrength]:
        """Get the strongest symbols from the top sectors."""
        rankings = self.rank_sectors(date, period)
        result: list[SymbolStrength] = []

        for sr in rankings[:top_n_sectors]:
            result.extend(sr.symbols[:top_n_per_sector])

        return result

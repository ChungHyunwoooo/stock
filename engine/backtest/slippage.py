"""SlippageModel protocol and implementations.

Follows the Port/Adapter pattern (same as BrokerPort) so that
BacktestRunner can swap slippage strategies via injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from engine.data.depth_cache import DepthCache


class SlippageModel(Protocol):
    """Slippage calculation protocol.

    Returns slippage as a fraction (e.g. 0.001 = 0.1%).
    Positive value = unfavourable (higher buy / lower sell price).
    """

    def calculate_slippage(
        self,
        symbol: str,
        side: str,
        order_size_usd: float,
        price: float,
    ) -> float: ...


class NoSlippage:
    """Default -- zero slippage."""

    def calculate_slippage(
        self,
        symbol: str,
        side: str,
        order_size_usd: float,
        price: float,
    ) -> float:
        return 0.0


class VolumeAdjustedSlippage:
    """Orderbook-depth-based slippage.

    ``slippage = base_spread + impact_factor * (order_size / depth_usd)``

    Falls back to 0.001 (0.1 %) when the depth cache has no data for the
    requested symbol.
    """

    _FALLBACK_SLIPPAGE = 0.001
    _IMPACT_FACTOR = 0.1

    def __init__(self, depth_cache: DepthCache) -> None:
        self._depth_cache = depth_cache

    def calculate_slippage(
        self,
        symbol: str,
        side: str,
        order_size_usd: float,
        price: float,
    ) -> float:
        stats = self._depth_cache.get_stats(symbol)
        if stats is None:
            return self._FALLBACK_SLIPPAGE

        base_spread: float = stats["avg_spread_pct"]
        depth_usd: float = stats["avg_depth_usd_10"]
        liquidity_ratio = order_size_usd / depth_usd if depth_usd > 0 else 1.0
        impact = self._IMPACT_FACTOR * liquidity_ratio
        return base_spread + impact

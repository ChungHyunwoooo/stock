"""Exchange fee model -- loads maker/taker rates from a JSON config file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_FEE_RATE = 0.001


def load_exchange_fees(path: Path) -> dict:
    """Load the exchange fees JSON file and return the raw dict."""
    with open(path) as f:
        return json.load(f)


class FeeModel:
    """Provides fee-rate lookups for exchange / market-type / side.

    If the requested exchange or market type is not found, a default rate
    of 0.001 (0.1 %) is returned.
    """

    def __init__(self, fee_path: Path = Path("config/exchange_fees.json")) -> None:
        self._fees = load_exchange_fees(fee_path)

    def get_fee_rate(
        self,
        exchange: str,
        market_type: str = "spot",
        side: str = "taker",
    ) -> float:
        """Return the fee rate for the given exchange/market/side.

        Falls back to ``_DEFAULT_FEE_RATE`` when the exchange or
        market type is not registered in the config.
        """
        exchange_fees = self._fees.get(exchange)
        if exchange_fees is None:
            logger.debug("Unknown exchange %s, using default fee %s", exchange, _DEFAULT_FEE_RATE)
            return _DEFAULT_FEE_RATE

        market_fees = exchange_fees.get(market_type)
        if market_fees is None:
            logger.debug(
                "Unknown market type %s for %s, using default fee %s",
                market_type, exchange, _DEFAULT_FEE_RATE,
            )
            return _DEFAULT_FEE_RATE

        return float(market_fees.get(side, _DEFAULT_FEE_RATE))

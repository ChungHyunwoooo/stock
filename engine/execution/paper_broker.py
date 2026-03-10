"""로컬 모의거래 브로커.

거래소 API 호출 없이 즉시 체결 시뮬레이션.
Upbit 모의거래용 (Upbit은 testnet 미제공).
"""

from __future__ import annotations

from typing import Any

from engine.core.models import BrokerKind, ExecutionRecord, OrderRequest
from engine.execution.broker_base import BaseBroker


class PaperBroker(BaseBroker):
    """로컬 모의거래 브로커 (즉시 체결)."""

    exchange_name = "paper"
    market_type = "spot"
    broker_kind = BrokerKind.paper

    def __init__(self, initial_balance: float = 10_000_000) -> None:
        self._balance = initial_balance
        self._positions: list[dict[str, Any]] = []

    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        return self._build_execution_record(
            order,
            status="filled",
            notes="paper",
        )

    def _fetch_raw_balance(self) -> dict[str, Any]:
        used = sum(
            p["entry_price"] * p["quantity"]
            for p in self._positions
        )
        return {
            "currency": "KRW",
            "total_equity": self._balance,
            "available": self._balance - used,
            "used": used,
            "unrealized_pnl": 0.0,
        }

    def _fetch_raw_positions(self) -> list[dict[str, Any]]:
        return list(self._positions)

    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        return True

    def _convert_symbol(self, symbol: str) -> str:
        return symbol

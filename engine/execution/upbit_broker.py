"""Upbit 현물 브로커 (pyupbit 기반).

Upbit은 testnet 없음 → 모의거래는 PaperBroker 사용.
"""

from __future__ import annotations

import logging
from typing import Any

import pyupbit

from engine.core.models import BrokerKind, ExecutionRecord, OrderRequest, SignalAction
from engine.execution.broker_base import BaseBroker

logger = logging.getLogger(__name__)


class UpbitBroker(BaseBroker):
    """Upbit 현물 브로커."""

    exchange_name = "upbit"
    market_type = "spot"
    broker_kind = BrokerKind.live

    def __init__(self, api_key: str, secret: str) -> None:
        self._upbit = pyupbit.Upbit(api_key, secret)

    # ── 거래소별 구현 ───────────────────────────────────────

    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        try:
            if order.action is SignalAction.entry:
                # 시장가 매수: 금액 기준 (KRW)
                krw_amount = order.price * order.quantity
                result = self._upbit.buy_market_order(converted_symbol, krw_amount)
            else:
                # 시장가 매도: 수량 기준
                result = self._upbit.sell_market_order(converted_symbol, order.quantity)

            if result is None or "error" in (result or {}):
                error_msg = (result or {}).get("error", {}).get("message", "알 수 없는 오류")
                logger.error("Upbit 주문 실패: %s — %s", converted_symbol, error_msg)
                return self._build_execution_record(
                    order, status="failed", notes=f"Upbit 오류: {error_msg}",
                )

            order_uuid = result.get("uuid", "")
            return self._build_execution_record(
                order,
                status="filled",
                notes=f"upbit spot",
                order_id=order_uuid,
            )
        except Exception as e:
            logger.error("Upbit 주문 예외: %s — %s", converted_symbol, e)
            return self._build_execution_record(order, status="failed", notes=str(e))

    def _fetch_raw_balance(self) -> dict[str, Any]:
        balances = self._upbit.get_balances()
        if balances is None:
            return {"currency": "KRW", "total_equity": 0, "available": 0, "used": 0, "unrealized_pnl": 0}

        krw_available = 0.0
        coin_value = 0.0

        for item in balances:
            currency = item.get("currency", "")
            bal = float(item.get("balance", 0))
            locked = float(item.get("locked", 0))

            if currency == "KRW":
                krw_available = bal
            else:
                avg_price = float(item.get("avg_buy_price", 0))
                coin_value += (bal + locked) * avg_price

        return {
            "currency": "KRW",
            "total_equity": krw_available + coin_value,
            "available": krw_available,
            "used": coin_value,
            "unrealized_pnl": 0.0,
        }

    def _fetch_raw_positions(self) -> list[dict[str, Any]]:
        balances = self._upbit.get_balances()
        if balances is None:
            return []

        positions = []
        for item in balances:
            currency = item.get("currency", "")
            if currency == "KRW":
                continue

            bal = float(item.get("balance", 0))
            locked = float(item.get("locked", 0))
            total_qty = bal + locked
            if total_qty <= 0:
                continue

            avg_price = float(item.get("avg_buy_price", 0))
            symbol = f"KRW-{currency}"

            # 현재가 조회
            current_price = pyupbit.get_current_price(symbol) or avg_price
            pnl = (current_price - avg_price) * total_qty if avg_price > 0 else 0

            positions.append({
                "symbol": f"{currency}/KRW",
                "side": "long",
                "quantity": total_qty,
                "entry_price": avg_price,
                "current_price": current_price,
                "pnl": round(pnl, 0),
            })

        return positions

    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        try:
            result = self._upbit.cancel_order(order_id)
            return result is not None and "error" not in (result or {})
        except Exception as e:
            logger.warning("Upbit 주문 취소 실패: %s — %s", order_id, e)
            return False

    def _convert_symbol(self, symbol: str) -> str:
        """BTC/KRW → KRW-BTC 변환."""
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            return f"{quote}-{base}"
        return symbol

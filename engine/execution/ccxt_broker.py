"""ccxt 기반 범용 거래소 브로커.

BinanceBroker의 ccxt 패턴을 일반화하여 bybit, okx 등
ccxt 지원 거래소를 config 설정만으로 활성화한다.
"""

from __future__ import annotations

import logging
from typing import Any

import ccxt

from engine.core.models import BrokerKind, ExecutionRecord, OrderRequest
from engine.execution.broker_base import BaseBroker

logger = logging.getLogger(__name__)

# 거래소별 선물 defaultType 매핑
_FUTURES_DEFAULT_TYPE: dict[str, str] = {
    "bybit": "swap",
    "okx": "swap",
}


class CcxtBroker(BaseBroker):
    """ccxt 기반 범용 거래소 브로커.

    지원 거래소: ccxt에 등록된 모든 거래소 (bybit, okx 등).
    binance는 기존 BinanceBroker 유지 (하위 호환).
    """

    broker_kind = BrokerKind.live

    def __init__(
        self,
        exchange: str,
        api_key: str,
        secret: str,
        market_type: str = "spot",
        testnet: bool = True,
        **extra: Any,
    ) -> None:
        self.exchange_name = exchange
        self.market_type = market_type
        self._testnet = testnet

        exchange_cls = getattr(ccxt, exchange)

        config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }

        # OKX passphrase 등 extra kwargs
        if "password" in extra:
            config["password"] = extra.pop("password")

        # 선물 옵션
        if market_type == "futures":
            default_type = _FUTURES_DEFAULT_TYPE.get(exchange, "swap")
            config["options"] = {"defaultType": default_type}

        self._exchange: ccxt.Exchange = exchange_cls(config)

        if testnet:
            self._exchange.set_sandbox_mode(True)
            self.broker_kind = BrokerKind.paper

    # ── 추상 메서드 구현 ─────────────────────────────────────

    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        side = "buy" if order.action.value == "entry" and order.side.value == "long" else "sell"
        if order.action.value == "exit":
            side = "sell" if order.side.value == "long" else "buy"

        order_type = order.metadata.get("order_type", "market")

        try:
            if order_type == "limit":
                result = self._exchange.create_order(
                    symbol=converted_symbol,
                    type="limit",
                    side=side,
                    amount=order.quantity,
                    price=order.price,
                    params={"postOnly": True},
                )
            else:
                result = self._exchange.create_order(
                    symbol=converted_symbol,
                    type="market",
                    side=side,
                    amount=order.quantity,
                )

            return self._build_execution_record(
                order,
                status="filled",
                notes=f"{self.exchange_name} {self.market_type} "
                      f"{'testnet' if self._testnet else 'live'}",
                order_id=str(result.get("id", "")),
            )
        except ccxt.InsufficientFunds as e:
            logger.error("잔고 부족: %s -- %s", converted_symbol, e)
            return self._build_execution_record(
                order, status="rejected", notes=f"잔고 부족: {e}",
            )
        except ccxt.BaseError as e:
            logger.error("[%s] 주문 실패: %s -- %s", self.exchange_name, converted_symbol, e)
            return self._build_execution_record(
                order, status="failed", notes=str(e),
            )

    def _fetch_raw_balance(self) -> dict[str, Any]:
        balance = self._exchange.fetch_balance()
        total = float(balance.get("total", {}).get("USDT", 0))
        free = float(balance.get("free", {}).get("USDT", 0))
        used = float(balance.get("used", {}).get("USDT", 0))
        return {
            "currency": "USDT",
            "total_equity": total,
            "available": free,
            "used": used,
            "unrealized_pnl": 0.0,
        }

    def _fetch_raw_positions(self) -> list[dict[str, Any]]:
        if self.market_type != "futures":
            return []
        try:
            raw_positions = self._exchange.fetch_positions()
            positions = []
            for p in raw_positions:
                qty = abs(float(p.get("contracts", 0) or 0))
                if qty == 0:
                    continue
                positions.append({
                    "symbol": p.get("symbol", ""),
                    "side": p.get("side", "long"),
                    "quantity": qty,
                    "entry_price": float(p.get("entryPrice", 0) or 0),
                    "current_price": float(p.get("markPrice", 0) or 0),
                    "pnl": float(p.get("unrealizedPnl", 0) or 0),
                    "leverage": int(p.get("leverage", 1) or 1),
                })
            return positions
        except ccxt.BaseError as e:
            logger.warning("[%s] 포지션 조회 실패: %s", self.exchange_name, e)
            return []

    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        try:
            self._exchange.cancel_order(order_id, converted_symbol)
            return True
        except ccxt.BaseError as e:
            logger.warning(
                "[%s] 주문 취소 실패: %s %s -- %s",
                self.exchange_name, order_id, converted_symbol, e,
            )
            return False

    def _convert_symbol(self, symbol: str) -> str:
        """ccxt unified symbol 그대로 반환."""
        return symbol

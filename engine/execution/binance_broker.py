"""Binance 현물/선물 브로커 (ccxt 기반).

testnet=True → Binance testnet (모의거래).
market_type="spot" | "futures"
"""

from __future__ import annotations

import logging
from typing import Any

import ccxt

from engine.core.models import BrokerKind, ExecutionRecord, OrderRequest
from engine.execution.broker_base import BaseBroker

logger = logging.getLogger(__name__)


class BinanceBroker(BaseBroker):
    """Binance 현물/선물 브로커."""

    exchange_name = "binance"
    broker_kind = BrokerKind.live

    def __init__(
        self,
        api_key: str,
        secret: str,
        market_type: str = "spot",
        testnet: bool = True,
    ) -> None:
        self.market_type = market_type
        self._testnet = testnet

        options: dict[str, Any] = {}
        if market_type == "futures":
            options["defaultType"] = "future"

        # 선물은 binanceusdm, 현물은 binance
        exchange_cls = ccxt.binanceusdm if market_type == "futures" else ccxt.binance
        self._exchange = exchange_cls({
            "apiKey": api_key,
            "secret": secret,
            "options": options,
            "enableRateLimit": True,
        })

        if testnet:
            self._exchange.enable_demo_trading(True)
            self.broker_kind = BrokerKind.paper

    # ── 거래소별 구현 ───────────────────────────────────────

    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        side = "buy" if order.action.value == "entry" and order.side.value == "long" else "sell"
        if order.action.value == "exit":
            side = "sell" if order.side.value == "long" else "buy"

        try:
            result = self._exchange.create_order(
                symbol=converted_symbol,
                type="market",
                side=side,
                amount=order.quantity,
            )

            filled_price = float(result.get("average", 0) or result.get("price", 0) or order.price)
            filled_qty = float(result.get("filled", 0) or order.quantity)
            fee_cost = 0.0
            if result.get("fee"):
                fee_cost = float(result["fee"].get("cost", 0))

            return self._build_execution_record(
                order,
                status="filled",
                notes=f"binance {self.market_type} {'testnet' if self._testnet else 'live'}",
                order_id=str(result.get("id", "")),
            )
        except ccxt.InsufficientFunds as e:
            logger.error("잔고 부족: %s — %s", converted_symbol, e)
            return self._build_execution_record(order, status="rejected", notes=f"잔고 부족: {e}")
        except ccxt.BaseError as e:
            logger.error("Binance 주문 실패: %s — %s", converted_symbol, e)
            return self._build_execution_record(order, status="failed", notes=str(e))

    def _fetch_raw_balance(self) -> dict[str, Any]:
        balance = self._exchange.fetch_balance()

        if self.market_type == "futures":
            total = float(balance.get("total", {}).get("USDT", 0))
            free = float(balance.get("free", {}).get("USDT", 0))
            used = float(balance.get("used", {}).get("USDT", 0))
            return {
                "currency": "USDT",
                "total_equity": total,
                "available": free,
                "used": used,
                "unrealized_pnl": 0.0,  # ccxt에서 별도 조회 필요
            }
        else:
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
            # 현물: 보유 코인을 포지션으로 변환
            balance = self._exchange.fetch_balance()
            positions = []
            for coin, amount in (balance.get("total", {}) or {}).items():
                amt = float(amount)
                if amt > 0 and coin not in ("USDT", "BUSD", "USD"):
                    positions.append({
                        "symbol": f"{coin}/USDT",
                        "side": "long",
                        "quantity": amt,
                        "entry_price": 0,  # 현물은 평균단가 별도 조회 필요
                        "current_price": 0,
                        "pnl": 0,
                    })
            return positions

        # 선물: ccxt fetch_positions
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
            logger.warning("포지션 조회 실패: %s", e)
            return []

    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        try:
            self._exchange.cancel_order(order_id, converted_symbol)
            return True
        except ccxt.BaseError as e:
            logger.warning("주문 취소 실패: %s %s — %s", order_id, converted_symbol, e)
            return False

    def _convert_symbol(self, symbol: str) -> str:
        """내부 심볼은 ccxt 표준 (BTC/USDT) 그대로 사용."""
        if self.market_type == "futures" and ":USDT" not in symbol:
            return f"{symbol}:USDT"
        return symbol

    # ── 선물 전용 ───────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """선물 레버리지 설정."""
        if self.market_type != "futures":
            logger.warning("현물에서는 레버리지 설정 불가")
            return
        converted = self._convert_symbol(symbol)
        try:
            self._exchange.set_leverage(leverage, converted)
            logger.info("레버리지 설정: %s → %dx", converted, leverage)
        except ccxt.BaseError as e:
            logger.error("레버리지 설정 실패: %s — %s", converted, e)

    def set_margin_mode(self, symbol: str, mode: str = "isolated") -> None:
        """선물 마진 모드 설정 (isolated/cross)."""
        if self.market_type != "futures":
            return
        converted = self._convert_symbol(symbol)
        try:
            self._exchange.set_margin_mode(mode, converted)
            logger.info("마진 모드: %s → %s", converted, mode)
        except ccxt.BaseError as e:
            logger.warning("마진 모드 설정 실패: %s — %s", converted, e)

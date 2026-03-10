"""브로커 공통 추상 기반.

모든 거래소 브로커가 상속. 공통 로직:
- 주문 검증 → 제출 → DB 기록 → 상태 갱신
- 잔고/포지션 정규화
- 손익 계산
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from engine.core.models import (
    BrokerKind,
    ExecutionRecord,
    OrderRequest,
    Position,
    PositionStatus,
    SignalAction,
    TradingRuntimeState,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class BaseBroker(ABC):
    """거래소 브로커 공통 기반.

    하위 클래스는 _place_order, _fetch_raw_balance, _cancel_raw,
    _convert_symbol, _fetch_raw_positions 만 구현하면 됨.
    """

    exchange_name: str = "base"
    market_type: str = "spot"  # spot / futures
    broker_kind: BrokerKind = BrokerKind.paper

    # ── 주문 실행 (공통 흐름) ───────────────────────────────

    def execute_order(
        self, order: OrderRequest, state: TradingRuntimeState,
    ) -> ExecutionRecord:
        """검증 → 심볼 변환 → 제출 → 상태 갱신 → 결과 반환."""
        self._validate_order(order)

        converted_symbol = self._convert_symbol(order.symbol)
        result = self._place_order(order, converted_symbol)

        self._update_position(order, result, state)
        state.touch()

        logger.info(
            "[%s] %s %s %s qty=%.6f price=%.2f → %s",
            self.exchange_name, order.action.value, order.side.value,
            order.symbol, order.quantity, order.price, result.status,
        )
        return result

    def _validate_order(self, order: OrderRequest) -> None:
        """공통 주문 검증."""
        if order.quantity <= 0:
            raise ValueError(f"수량은 0보다 커야 합니다: {order.quantity}")
        if order.price < 0:
            raise ValueError(f"가격은 0 이상이어야 합니다: {order.price}")

    def _update_position(
        self,
        order: OrderRequest,
        result: ExecutionRecord,
        state: TradingRuntimeState,
    ) -> None:
        """주문 결과로 포지션 상태 갱신."""
        if result.status != "filled":
            return

        if order.action is SignalAction.entry:
            position = Position(
                position_id=uuid4().hex[:12],
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                entry_price=order.price,
            )
            state.positions.append(position)
        else:
            for position in state.positions:
                if (
                    position.symbol == order.symbol
                    and position.status is PositionStatus.open
                ):
                    position.status = PositionStatus.closed
                    position.closed_at = utc_now_iso()
                    position.exit_price = order.price
                    break

    def _build_execution_record(
        self,
        order: OrderRequest,
        status: str = "filled",
        notes: str = "",
        order_id: str | None = None,
    ) -> ExecutionRecord:
        """ExecutionRecord 생성 헬퍼."""
        return ExecutionRecord(
            order_id=order_id or uuid4().hex[:12],
            signal_id=order.signal_id,
            symbol=order.symbol,
            action=order.action,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            broker=self.broker_kind,
            status=status,
            notes=notes,
        )

    # ── 잔고/포지션 (정규화) ───────────────────────────────

    def fetch_balance(self) -> dict[str, Any]:
        """정규화된 잔고 조회."""
        raw = self._fetch_raw_balance()
        positions = self._fetch_raw_positions()
        return self._normalize_balance(raw, positions)

    def _normalize_balance(
        self,
        raw: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """거래소 원시 잔고 → 정규화 포맷."""
        total = float(raw.get("total_equity", 0))
        available = float(raw.get("available", 0))
        used = float(raw.get("used", 0))
        unrealized = float(raw.get("unrealized_pnl", 0))

        return {
            "exchange": self.exchange_name,
            "market_type": self.market_type,
            "currency": raw.get("currency", "USDT"),
            "total_equity": total,
            "available": available,
            "used": used,
            "unrealized_pnl": unrealized,
            "positions": positions,
        }

    def fetch_total_equity(self) -> float:
        """총 평가액."""
        balance = self.fetch_balance()
        return balance["total_equity"]

    def fetch_available(self) -> float:
        """주문 가능 금액."""
        balance = self.fetch_balance()
        return balance["available"]

    def fetch_open_positions(self) -> list[dict[str, Any]]:
        """열린 포지션 목록."""
        return self._fetch_raw_positions()

    # ── 주문 취소 (공통 흐름) ───────────────────────────────

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """주문 취소."""
        converted = self._convert_symbol(symbol)
        success = self._cancel_raw(order_id, converted)
        if success:
            logger.info("[%s] 주문 취소: %s %s", self.exchange_name, order_id, symbol)
        return success

    # ── 손익 계산 (공통) ───────────────────────────────────

    @staticmethod
    def calc_profit(
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        entry_fee: float = 0,
        exit_fee: float = 0,
    ) -> dict[str, float]:
        """손익 계산."""
        if side == "long":
            profit_abs = (exit_price - entry_price) * quantity - entry_fee - exit_fee
        else:
            profit_abs = (entry_price - exit_price) * quantity - entry_fee - exit_fee

        stake = entry_price * quantity
        profit_pct = (profit_abs / stake * 100) if stake > 0 else 0.0

        return {
            "profit_abs": round(profit_abs, 2),
            "profit_pct": round(profit_pct, 4),
            "stake_amount": round(stake, 2),
        }

    # ── 추상 메서드 (거래소별 구현) ─────────────────────────

    @abstractmethod
    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        """실제 API 주문 제출."""
        ...

    @abstractmethod
    def _fetch_raw_balance(self) -> dict[str, Any]:
        """거래소 원시 잔고 조회."""
        ...

    @abstractmethod
    def _fetch_raw_positions(self) -> list[dict[str, Any]]:
        """거래소 원시 포지션 조회."""
        ...

    @abstractmethod
    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        """거래소 원시 주문 취소."""
        ...

    @abstractmethod
    def _convert_symbol(self, symbol: str) -> str:
        """내부 심볼 → 거래소 심볼 변환."""
        ...

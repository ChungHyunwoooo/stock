from __future__ import annotations

from typing import Protocol

from engine.domain.trading.models import (
    ExecutionRecord,
    OrderRequest,
    PendingOrder,
    TradingRuntimeState,
    TradingSignal,
)


class RuntimeStorePort(Protocol):
    def load(self) -> TradingRuntimeState:
        ...

    def save(self, state: TradingRuntimeState) -> None:
        ...


class NotificationPort(Protocol):
    def send_signal(self, signal: TradingSignal, mode_label: str) -> bool:
        ...

    def send_pending(self, pending: PendingOrder) -> bool:
        ...

    def send_execution(self, execution: ExecutionRecord) -> bool:
        ...

    def send_text(self, message: str) -> bool:
        ...


class BrokerPort(Protocol):
    def execute_order(self, order: OrderRequest, state: TradingRuntimeState) -> ExecutionRecord:
        ...

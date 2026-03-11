
from typing import Any, Protocol

from engine.core.models import (
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

    def send_performance_alert(self, snapshot: "PerformanceSnapshot") -> bool:
        ...


class BrokerPort(Protocol):
    def execute_order(self, order: OrderRequest, state: TradingRuntimeState) -> ExecutionRecord:
        ...

    def fetch_balance(self) -> dict[str, Any]:
        ...

    def fetch_total_equity(self) -> float:
        ...

    def fetch_available(self) -> float:
        ...

    def fetch_open_positions(self) -> list[dict[str, Any]]:
        ...

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        ...

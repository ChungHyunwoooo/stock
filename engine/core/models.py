
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class TradingMode(str, Enum):
    alert_only = "alert_only"
    semi_auto = "semi_auto"
    auto = "auto"

class BrokerKind(str, Enum):
    paper = "paper"
    live = "live"

class SignalAction(str, Enum):
    entry = "entry"
    exit = "exit"

class TradeSide(str, Enum):
    long = "long"
    short = "short"

class PendingState(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"

class PositionStatus(str, Enum):
    open = "open"
    closed = "closed"

@dataclass(slots=True)
class TradingSignal:
    strategy_id: str
    symbol: str
    timeframe: str
    action: SignalAction
    side: TradeSide
    entry_price: float
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=utc_now_iso)

@dataclass(slots=True)
class OrderRequest:
    signal_id: str
    symbol: str
    action: SignalAction
    side: TradeSide
    quantity: float
    price: float
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)

@dataclass(slots=True)
class ExecutionRecord:
    order_id: str
    signal_id: str
    symbol: str
    action: SignalAction
    side: TradeSide
    quantity: float
    price: float
    broker: BrokerKind
    status: str
    notes: str = ""
    executed_at: str = field(default_factory=utc_now_iso)

@dataclass(slots=True)
class Position:
    position_id: str
    symbol: str
    side: TradeSide
    quantity: float
    entry_price: float
    status: PositionStatus = PositionStatus.open
    opened_at: str = field(default_factory=utc_now_iso)
    closed_at: str | None = None
    exit_price: float | None = None

@dataclass(slots=True)
class PendingOrder:
    pending_id: str
    signal: TradingSignal
    quantity: float
    requested_at: str = field(default_factory=utc_now_iso)
    state: PendingState = PendingState.pending
    decided_at: str | None = None

@dataclass(slots=True)
class TradingRuntimeState:
    mode: TradingMode = TradingMode.alert_only
    broker: BrokerKind = BrokerKind.paper
    paused: bool = False
    automation_enabled: bool = True
    pending_orders: list[PendingOrder] = field(default_factory=list)
    executions: list[ExecutionRecord] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

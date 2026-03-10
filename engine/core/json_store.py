
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.core.models import (
    BrokerKind,
    ExecutionRecord,
    PendingOrder,
    PendingState,
    Position,
    PositionStatus,
    SignalAction,
    TradeSide,
    TradingMode,
    TradingRuntimeState,
    TradingSignal,
)

class JsonRuntimeStore:
    def __init__(self, path: str | Path = "state/runtime_state.json") -> None:
        self.path = Path(path)

    def load(self) -> TradingRuntimeState:
        if not self.path.exists():
            return TradingRuntimeState()
        data = json.loads(self.path.read_text())
        return self._state_from_dict(data)

    def save(self, state: TradingRuntimeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state_to_dict(state), indent=2))

    def _state_to_dict(self, state: TradingRuntimeState) -> dict[str, Any]:
        return asdict(state)

    def _state_from_dict(self, data: dict[str, Any]) -> TradingRuntimeState:
        pending_orders = [self._pending_from_dict(item) for item in data.get("pending_orders", [])]
        executions = [self._execution_from_dict(item) for item in data.get("executions", [])]
        positions = [self._position_from_dict(item) for item in data.get("positions", [])]
        return TradingRuntimeState(
            mode=TradingMode(data.get("mode", TradingMode.alert_only.value)),
            broker=BrokerKind(data.get("broker", BrokerKind.paper.value)),
            paused=bool(data.get("paused", False)),
            automation_enabled=bool(data.get("automation_enabled", True)),
            pending_orders=pending_orders,
            executions=executions,
            positions=positions,
            updated_at=data.get("updated_at", ""),
        )

    def _pending_from_dict(self, data: dict[str, Any]) -> PendingOrder:
        return PendingOrder(
            pending_id=data["pending_id"],
            signal=self._signal_from_dict(data["signal"]),
            quantity=float(data["quantity"]),
            requested_at=data.get("requested_at", ""),
            state=PendingState(data.get("state", PendingState.pending.value)),
            decided_at=data.get("decided_at"),
        )

    def _execution_from_dict(self, data: dict[str, Any]) -> ExecutionRecord:
        return ExecutionRecord(
            order_id=data["order_id"],
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            action=SignalAction(data["action"]),
            side=TradeSide(data["side"]),
            quantity=float(data["quantity"]),
            price=float(data["price"]),
            broker=BrokerKind(data["broker"]),
            status=data["status"],
            notes=data.get("notes", ""),
            executed_at=data.get("executed_at", ""),
        )

    def _position_from_dict(self, data: dict[str, Any]) -> Position:
        return Position(
            position_id=data["position_id"],
            symbol=data["symbol"],
            side=TradeSide(data["side"]),
            quantity=float(data["quantity"]),
            entry_price=float(data["entry_price"]),
            status=PositionStatus(data.get("status", PositionStatus.open.value)),
            opened_at=data.get("opened_at", ""),
            closed_at=data.get("closed_at"),
            exit_price=float(data["exit_price"]) if data.get("exit_price") is not None else None,
        )

    def _signal_from_dict(self, data: dict[str, Any]) -> TradingSignal:
        return TradingSignal(
            strategy_id=data["strategy_id"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            action=SignalAction(data["action"]),
            side=TradeSide(data["side"]),
            entry_price=float(data["entry_price"]),
            stop_loss=float(data["stop_loss"]) if data.get("stop_loss") is not None else None,
            take_profits=[float(v) for v in data.get("take_profits", [])],
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", ""),
            metadata=data.get("metadata", {}),
            signal_id=data.get("signal_id", ""),
            created_at=data.get("created_at", ""),
        )

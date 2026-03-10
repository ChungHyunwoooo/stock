
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

class PaperBroker:
    def execute_order(self, order: OrderRequest, state: TradingRuntimeState) -> ExecutionRecord:
        if order.action is SignalAction.entry:
            position = Position(
                position_id=uuid4().hex[:12],
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                entry_price=order.price,
            )
            state.positions.append(position)
            status = "filled"
            notes = "paper entry"
        else:
            status = "filled"
            notes = "paper exit"
            for position in state.positions:
                if position.symbol == order.symbol and position.status is PositionStatus.open:
                    position.status = PositionStatus.closed
                    position.closed_at = utc_now_iso()
                    position.exit_price = order.price
                    break

        state.touch()
        return ExecutionRecord(
            order_id=uuid4().hex[:12],
            signal_id=order.signal_id,
            symbol=order.symbol,
            action=order.action,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            broker=BrokerKind.paper,
            status=status,
            notes=notes,
        )

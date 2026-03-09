from __future__ import annotations

from engine.application.trading.exceptions import PendingOrderNotFoundError
from engine.domain.trading.models import OrderRequest, PendingOrder, PendingState, TradingMode, TradingRuntimeState, utc_now_iso
from engine.domain.trading.ports import BrokerPort, NotificationPort, RuntimeStorePort


class TradingControlService:
    def __init__(
        self,
        runtime_store: RuntimeStorePort,
        notifier: NotificationPort,
        broker: BrokerPort,
    ) -> None:
        self.runtime_store = runtime_store
        self.notifier = notifier
        self.broker = broker

    def get_state(self) -> TradingRuntimeState:
        return self.runtime_store.load()

    def set_mode(self, mode: TradingMode) -> TradingRuntimeState:
        state = self.runtime_store.load()
        state.mode = mode
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_text(f"Trading mode set to `{mode.value}`.")
        return state

    def pause(self) -> TradingRuntimeState:
        state = self.runtime_store.load()
        state.paused = True
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_text("Trading runtime paused.")
        return state

    def resume(self) -> TradingRuntimeState:
        state = self.runtime_store.load()
        state.paused = False
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_text("Trading runtime resumed.")
        return state

    def set_automation(self, enabled: bool) -> TradingRuntimeState:
        state = self.runtime_store.load()
        state.automation_enabled = enabled
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_text(f"Automation {'enabled' if enabled else 'disabled'}.")
        return state

    def approve_pending(self, pending_id: str) -> TradingRuntimeState:
        state = self.runtime_store.load()
        pending = self._find_pending(state, pending_id)
        order = OrderRequest(
            signal_id=pending.signal.signal_id,
            symbol=pending.signal.symbol,
            action=pending.signal.action,
            side=pending.signal.side,
            quantity=pending.quantity,
            price=pending.signal.entry_price,
            stop_loss=pending.signal.stop_loss,
            take_profits=list(pending.signal.take_profits),
            metadata=dict(pending.signal.metadata),
        )
        execution = self.broker.execute_order(order, state)
        state.executions.append(execution)
        pending.state = PendingState.executed
        pending.decided_at = utc_now_iso()
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_execution(execution)
        return state

    def reject_pending(self, pending_id: str) -> TradingRuntimeState:
        state = self.runtime_store.load()
        pending = self._find_pending(state, pending_id)
        pending.state = PendingState.rejected
        pending.decided_at = utc_now_iso()
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_text(f"Pending order `{pending_id}` rejected.")
        return state

    @staticmethod
    def _find_pending(state: TradingRuntimeState, pending_id: str) -> PendingOrder:
        for pending in state.pending_orders:
            if pending.pending_id == pending_id and pending.state is PendingState.pending:
                return pending
        raise PendingOrderNotFoundError(f"Pending order not found: {pending_id}")

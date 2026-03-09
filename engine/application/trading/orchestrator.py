from __future__ import annotations

from uuid import uuid4

from engine.domain.trading.models import OrderRequest, PendingOrder, TradingMode, TradingRuntimeState, TradingSignal
from engine.domain.trading.ports import BrokerPort, NotificationPort, RuntimeStorePort


class TradingOrchestrator:
    def __init__(
        self,
        runtime_store: RuntimeStorePort,
        notifier: NotificationPort,
        broker: BrokerPort,
    ) -> None:
        self.runtime_store = runtime_store
        self.notifier = notifier
        self.broker = broker

    def process_signal(self, signal: TradingSignal, quantity: float = 1.0) -> TradingRuntimeState:
        state = self.runtime_store.load()
        state.touch()

        if state.paused or not state.automation_enabled:
            self.notifier.send_signal(signal, mode_label="paused")
            self.notifier.send_text(
                f"Signal {signal.signal_id} received for {signal.symbol}, but runtime is paused."
            )
            self.runtime_store.save(state)
            return state

        if state.mode is TradingMode.alert_only:
            self.notifier.send_signal(signal, mode_label=state.mode.value)
            self.runtime_store.save(state)
            return state

        if state.mode is TradingMode.semi_auto:
            pending = PendingOrder(
                pending_id=uuid4().hex[:12],
                signal=signal,
                quantity=quantity,
            )
            state.pending_orders.append(pending)
            self.runtime_store.save(state)
            self.notifier.send_signal(signal, mode_label=state.mode.value)
            self.notifier.send_pending(pending)
            return state

        order = self._build_order(signal, quantity)
        execution = self.broker.execute_order(order, state)
        state.executions.append(execution)
        state.touch()
        self.runtime_store.save(state)
        self.notifier.send_signal(signal, mode_label=state.mode.value)
        self.notifier.send_execution(execution)
        return state

    @staticmethod
    def _build_order(signal: TradingSignal, quantity: float) -> OrderRequest:
        return OrderRequest(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            action=signal.action,
            side=signal.side,
            quantity=quantity,
            price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profits=list(signal.take_profits),
            metadata=dict(signal.metadata),
        )

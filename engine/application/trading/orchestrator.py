
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pandas as pd

from engine.core.models import OrderRequest, PendingOrder, TradingMode, TradingRuntimeState, TradingSignal
from engine.core.ports import BrokerPort, NotificationPort, RuntimeStorePort

if TYPE_CHECKING:
    from engine.strategy.portfolio_risk import PortfolioRiskManager

class TradingOrchestrator:
    def __init__(
        self,
        runtime_store: RuntimeStorePort,
        notifier: NotificationPort,
        broker: BrokerPort,
        portfolio_risk: PortfolioRiskManager | None = None,
    ) -> None:
        self.runtime_store = runtime_store
        self.notifier = notifier
        self.broker = broker
        self.portfolio_risk = portfolio_risk

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

        if signal.strategy_id in state.paused_strategies:
            self.notifier.send_text(
                f"Signal {signal.signal_id} for {signal.symbol} skipped: "
                f"strategy {signal.strategy_id} is paused (performance degradation)."
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

        # Portfolio risk correlation gate (full_auto only)
        if self.portfolio_risk is not None:
            signal_returns = self._get_signal_returns(signal)
            allowed, reason = self.portfolio_risk.check_correlation_gate(
                signal.strategy_id, signal_returns,
            )
            if not allowed:
                self.notifier.send_text(
                    f"[PortfolioRisk] {signal.symbol} entry blocked: {reason}"
                )
                self.runtime_store.save(state)
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
    def _get_signal_returns(signal: TradingSignal) -> pd.Series:
        """signal.metadata에서 수익률 시계열 조회, 없으면 빈 Series."""
        returns = signal.metadata.get("returns")
        if isinstance(returns, pd.Series):
            return returns
        return pd.Series(dtype=float)

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

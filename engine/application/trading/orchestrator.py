
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pandas as pd

from engine.core.models import OrderRequest, PendingOrder, TradingMode, TradingRuntimeState, TradingSignal
from engine.core.ports import BrokerPort, NotificationPort, RuntimeStorePort

if TYPE_CHECKING:
    from engine.notifications.event_notifier import EventNotifier
    from engine.strategy.mtf_filter import MTFConfirmationGate
    from engine.strategy.portfolio_risk import PortfolioRiskManager
    from engine.strategy.position_sizer import PositionSizer


class TradingOrchestrator:
    def __init__(
        self,
        runtime_store: RuntimeStorePort,
        notifier: NotificationPort,
        broker: BrokerPort,
        position_sizer: PositionSizer | None = None,
        portfolio_risk: PortfolioRiskManager | None = None,
        event_notifier: EventNotifier | None = None,
        mtf_filter: MTFConfirmationGate | None = None,
    ) -> None:
        self.runtime_store = runtime_store
        self.notifier = notifier
        self.broker = broker
        self.position_sizer = position_sizer
        self.portfolio_risk = portfolio_risk
        self.event_notifier = event_notifier
        self.mtf_filter = mtf_filter

    def process_signal(self, signal: TradingSignal) -> TradingRuntimeState:
        # Strip non-serializable objects from metadata (used by sizer, not persisted)
        _transient_meta = {}
        for key in self._META_EXCLUDE:
            if key in signal.metadata:
                _transient_meta[key] = signal.metadata.pop(key)

        try:
            return self._process_signal_inner(signal, _transient_meta)
        finally:
            # Restore transient metadata (caller may still need it)
            signal.metadata.update(_transient_meta)

    def _process_signal_inner(
        self, signal: TradingSignal, _transient: dict,
    ) -> TradingRuntimeState:
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

        # --- Sizing validation for execution paths ---
        if state.mode in (TradingMode.semi_auto, TradingMode.auto):
            if self.position_sizer is None:
                raise ValueError(
                    "position_sizer is required for semi_auto/auto mode"
                )
            if self.portfolio_risk is None:
                raise ValueError(
                    "portfolio_risk is required for semi_auto/auto mode"
                )

        if state.mode is TradingMode.semi_auto:
            quantity = self._compute_quantity(signal, _transient)
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

        # --- full_auto path ---

        # Portfolio risk correlation gate
        if self.portfolio_risk is not None:
            signal_returns = _transient.get("returns")
            if not isinstance(signal_returns, pd.Series):
                signal_returns = pd.Series(dtype=float)
            allowed, reason = self.portfolio_risk.check_correlation_gate(
                signal.strategy_id, signal_returns,
            )
            if not allowed:
                self.notifier.send_text(
                    f"[PortfolioRisk] {signal.symbol} entry blocked: {reason}"
                )
                self.runtime_store.save(state)
                return state

        # Unregistered strategy check
        weights = self.portfolio_risk.get_allocation_weights()
        if signal.strategy_id not in weights:
            self.notifier.send_text(
                f"[PortfolioRisk] {signal.strategy_id} entry blocked: unregistered strategy"
            )
            self.runtime_store.save(state)
            return state

        # Position sizing
        allocation_weight = weights[signal.strategy_id]
        ohlcv_df = _transient.get("ohlcv_df")
        if not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty:
            self.notifier.send_text(
                f"[Sizer] {signal.symbol} entry blocked: no OHLCV data in signal"
            )
            self.runtime_store.save(state)
            return state

        capital = self.broker.fetch_available()
        size_result = self.position_sizer.calculate(
            df=ohlcv_df,
            entry_price=signal.entry_price,
            side=signal.side.value,
            capital=capital,
            timeframe=signal.timeframe,
            allocation_weight=allocation_weight,
        )
        quantity = size_result.quantity

        # MTF confirmation gate
        if self.mtf_filter is not None:
            aligned, reason = self.mtf_filter.check_alignment(
                signal.symbol, signal.side, signal.timeframe,
            )
            if not aligned:
                self.notifier.send_text(
                    f"[MTF] {signal.symbol} entry blocked: {reason}"
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
        if self.event_notifier:
            self.event_notifier.notify_execution(execution)
        return state

    def _compute_quantity(self, signal: TradingSignal, _transient: dict) -> float:
        """Compute quantity using PositionSizer for semi_auto/auto paths."""
        weights = self.portfolio_risk.get_allocation_weights()
        allocation_weight = weights.get(signal.strategy_id, 1.0)

        ohlcv_df = _transient.get("ohlcv_df")
        if not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty:
            return 1.0  # fallback for semi_auto without OHLCV

        capital = self.broker.fetch_available()
        size_result = self.position_sizer.calculate(
            df=ohlcv_df,
            entry_price=signal.entry_price,
            side=signal.side.value,
            capital=capital,
            timeframe=signal.timeframe,
            allocation_weight=allocation_weight,
        )
        return size_result.quantity

    # Keys excluded from order metadata (non-serializable objects)
    _META_EXCLUDE = {"ohlcv_df", "returns"}

    @staticmethod
    def _build_order(signal: TradingSignal, quantity: float) -> OrderRequest:
        filtered_meta = {
            k: v for k, v in signal.metadata.items()
            if k not in TradingOrchestrator._META_EXCLUDE
        }
        return OrderRequest(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            action=signal.action,
            side=signal.side,
            quantity=quantity,
            price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profits=list(signal.take_profits),
            metadata=filtered_meta,
        )

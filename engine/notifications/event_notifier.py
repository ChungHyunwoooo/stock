"""Event-specific Discord notification formatter.

Wraps a NotificationPort to send structured messages for:
- Trade executions
- Lifecycle state transitions
- System errors/warnings
- Backtest completion results
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.core.models import ExecutionRecord
    from engine.core.ports import NotificationPort

logger = logging.getLogger(__name__)


class EventNotifier:
    """Formats and dispatches event-specific messages via NotificationPort.send_text()."""

    def __init__(self, notifier: NotificationPort) -> None:
        self._notifier = notifier

    def notify_execution(self, execution: ExecutionRecord) -> bool:
        """Send a trade execution notification."""
        msg = (
            f"[EXECUTION] {execution.symbol} {execution.side.value.upper()} "
            f"{execution.quantity} @ {execution.price:,.4f} ({execution.broker.value})"
        )
        return self._notifier.send_text(msg)

    def notify_lifecycle_transition(
        self,
        strategy_id: str,
        from_status: str,
        to_status: str,
        reason: str = "",
    ) -> bool:
        """Send a lifecycle state transition notification."""
        msg = f"[LIFECYCLE] {strategy_id}: {from_status} -> {to_status}"
        if reason:
            msg += f" ({reason})"
        return self._notifier.send_text(msg)

    def notify_system_error(
        self,
        component: str,
        error: str,
        severity: str = "WARNING",
    ) -> bool:
        """Send a system error/warning notification."""
        severity = severity.upper()
        msg = f"[{severity}] {component}: {error}"
        return self._notifier.send_text(msg)

    def notify_backtest_complete(
        self,
        strategy_id: str,
        symbol: str,
        sharpe: float | None,
        total_return: float,
        max_dd: float | None,
    ) -> bool:
        """Send a backtest completion result notification."""
        sharpe_str = f"Sharpe {sharpe:.2f}" if sharpe is not None else "Sharpe N/A"
        dd_str = f"MaxDD {max_dd:+.1%}" if max_dd is not None else "MaxDD N/A"
        msg = (
            f"[BACKTEST] {strategy_id} {symbol} -- "
            f"{sharpe_str}, Return {total_return:+.1%}, {dd_str}"
        )
        return self._notifier.send_text(msg)

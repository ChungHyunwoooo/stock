
from __future__ import annotations

from datetime import datetime, timezone

from engine.application.trading.trading_control import TradingControlService
from engine.strategy.lifecycle_manager import LifecycleManager


def format_status_embed(control: TradingControlService, lifecycle: LifecycleManager) -> str:
    """Build a comprehensive status message for Discord /status command."""
    state = control.get_state()
    lines: list[str] = []

    # -- Runtime section --
    lines.append("``` Runtime ```")
    lines.append(f"mode={state.mode.value}  paused={state.paused}  automation={state.automation_enabled}")

    # -- Open positions section --
    open_positions = [p for p in state.positions if p.status.value == "open"]
    lines.append("")
    lines.append("``` Positions ```")
    if not open_positions:
        lines.append("No open positions")
    else:
        for p in open_positions:
            pnl_pct = ((p.exit_price or p.entry_price) / p.entry_price - 1) * 100 if p.entry_price else 0.0
            lines.append(f"{p.symbol}  {p.side.value}  entry={p.entry_price}  PnL={pnl_pct:+.2f}%")

    # -- Daily PnL section --
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_execs = [
        e for e in state.executions
        if e.executed_at[:10] == today_utc
    ]
    lines.append("")
    lines.append("``` Daily PnL ```")
    if not today_execs:
        lines.append("No trades today")
    else:
        realized = sum(float(e.notes) for e in today_execs if _is_numeric(e.notes))
        lines.append(f"Trades: {len(today_execs)}  Realized PnL: {realized:+.4f}")

    # -- Strategy status section --
    lines.append("")
    lines.append("``` Strategies ```")
    try:
        strategies = lifecycle.list_by_status()
        if not strategies:
            lines.append("No strategies registered")
        else:
            counts: dict[str, int] = {}
            for s in strategies:
                st = s.get("status", "unknown")
                counts[st] = counts.get(st, 0) + 1
            lines.append("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    except (FileNotFoundError, Exception) as exc:
        lines.append(f"Strategy info unavailable ({type(exc).__name__})")

    # -- Timestamp --
    lines.append("")
    lines.append(f"Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

    return "\n".join(lines)


def _is_numeric(value: str) -> bool:
    """Check if a string can be parsed as float."""
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def format_runtime_state(control: TradingControlService) -> str:
    state = control.get_state()
    pending = [p for p in state.pending_orders if p.state.value == "pending"]
    open_positions = [p for p in state.positions if p.status.value == "open"]
    return (
        f"mode={state.mode.value}\n"
        f"paused={state.paused}\n"
        f"automation_enabled={state.automation_enabled}\n"
        f"broker={state.broker.value}\n"
        f"pending={len(pending)}\n"
        f"open_positions={len(open_positions)}\n"
        f"executions={len(state.executions)}"
    )

def format_pending_list(control: TradingControlService, limit: int = 20) -> str:
    state = control.get_state()
    items = [p for p in state.pending_orders if p.state.value == "pending"]
    if not items:
        return "no pending orders"
    return "\n".join(
        f"{item.pending_id}: {item.signal.symbol} {item.signal.action.value} {item.signal.side.value} qty={item.quantity}"
        for item in items[:limit]
    )


from engine.application.trading.trading_control import TradingControlService

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

"""Dashboard data access layer wrapping existing repos.

Provides unified data interface for Streamlit dashboard pages.
No FastAPI -- direct repo imports (anti-pattern compliance).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from engine.core.json_store import JsonRuntimeStore
from engine.core.repository import TradeRepository
from engine.strategy.lifecycle_manager import LifecycleManager


class DashboardDataService:
    """Dashboard-specific data provider wrapping existing repositories."""

    def __init__(
        self,
        lifecycle: LifecycleManager | None = None,
        trade_repo: TradeRepository | None = None,
        runtime_store: JsonRuntimeStore | None = None,
    ) -> None:
        self._lifecycle = lifecycle or LifecycleManager()
        self._trade_repo = trade_repo or TradeRepository()
        self._runtime_store = runtime_store or JsonRuntimeStore()

    # -- Lifecycle -----------------------------------------------------------

    def get_lifecycle_summary(self) -> list[dict]:
        """Return all strategies from registry."""
        return self._lifecycle.list_by_status(None)

    def get_lifecycle_counts(self) -> dict[str, int]:
        """Return strategy count per status."""
        strategies = self._lifecycle.list_by_status(None)
        return dict(Counter(s.get("status", "unknown") for s in strategies))

    # -- Portfolio -----------------------------------------------------------

    def get_portfolio_summary(self, session: object) -> dict:
        """Return aggregated trade summary across all strategies."""
        return self._trade_repo.summary(session)

    def get_strategy_pnl(self, session: object, strategy_id: str) -> dict:
        """Return trade summary for a specific strategy."""
        return self._trade_repo.summary(session, strategy_name=strategy_id)

    # -- System Health -------------------------------------------------------

    def get_system_health(self) -> dict:
        """Return runtime state as a plain dict."""
        state = self._runtime_store.load()
        return {
            "mode": state.mode.value,
            "paused": state.paused,
            "paused_strategies": state.paused_strategies,
            "updated_at": state.updated_at,
        }

    # -- Sweep Status --------------------------------------------------------

    def get_sweep_status(self, state_dir: Path | None = None) -> dict | None:
        """Return sweep progress from state/sweep_status.json.

        Parameters
        ----------
        state_dir : Path | None
            Override for state directory (for testing). Defaults to ``state/``.

        Returns ``None`` if file missing or corrupted.
        """
        target_dir = state_dir or Path("state")
        status_path = target_dir / "sweep_status.json"
        if not status_path.exists():
            return None
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # -- Positions / Trades --------------------------------------------------

    def get_open_positions(self, session: object) -> list[dict]:
        """Return open positions as list of dicts."""
        trades = self._trade_repo.list_open(session)
        return [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "quantity": t.entry_quantity,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "entry_at": t.entry_at,
                "strategy": t.strategy_name,
            }
            for t in trades
        ]

    def get_closed_trades(self, session: object, limit: int = 50) -> list[dict]:
        """Return closed trades as list of dicts."""
        trades = self._trade_repo.list_closed(session, limit=limit)
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "strategy": t.strategy_name,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.entry_quantity,
                "pnl": t.profit_abs or 0,
                "pnl_pct": t.profit_pct or 0,
                "entry_at": t.entry_at,
                "exit_at": t.exit_at,
                "exit_reason": t.exit_reason,
                "duration_sec": t.duration_seconds or 0,
            }
            for t in trades
        ]

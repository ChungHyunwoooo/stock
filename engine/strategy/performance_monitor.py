"""Strategy performance monitor -- rolling window metrics vs backtest baseline.

Runs as a daemon thread, evaluating active strategies every check_interval_seconds.
Completely decoupled from TradingOrchestrator; monitor down != trading down.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.core.ports import NotificationPort, RuntimeStorePort
    from engine.core.repository import BacktestRepository, TradeRepository
    from engine.strategy.lifecycle_manager import LifecycleManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config / Snapshot
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PerformanceConfig:
    warning_threshold: float = 0.15
    critical_sharpe: float = -0.5
    rolling_window: int = 20
    rolling_window_extended: int = 30
    check_interval_seconds: int = 900


@dataclass(slots=True)
class PerformanceSnapshot:
    strategy_id: str
    rolling_sharpe: float | None = None
    rolling_win_rate: float | None = None
    baseline_sharpe: float | None = None
    baseline_win_rate: float | None = None
    degradation_pct_sharpe: float | None = None
    degradation_pct_win_rate: float | None = None
    alert_level: str = "none"  # none / warning / critical


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class StrategyPerformanceMonitor:
    """Rolling window performance evaluator for active strategies."""

    def __init__(
        self,
        trade_repo: TradeRepository,
        backtest_repo: BacktestRepository,
        lifecycle: LifecycleManager,
        runtime_store: RuntimeStorePort,
        notifier: NotificationPort,
        config: PerformanceConfig | None = None,
    ) -> None:
        self.trade_repo = trade_repo
        self.backtest_repo = backtest_repo
        self.lifecycle = lifecycle
        self.runtime_store = runtime_store
        self.notifier = notifier
        self.config = config or PerformanceConfig()

    # -- metrics -------------------------------------------------------------

    @staticmethod
    def _compute_rolling_metrics(
        trades: list, window: int,
    ) -> tuple[float | None, float | None]:
        """Compute Sharpe and win rate from recent trades.

        Returns (None, None) if len(trades) < window.
        Uses pure Python (no numpy).
        """
        if len(trades) < window:
            return None, None

        recent = trades[-window:]
        profits = [t.profit_pct for t in recent]

        n = len(profits)
        mean = sum(profits) / n
        variance = sum((p - mean) ** 2 for p in profits) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0

        sharpe = mean / std if std > 0 else 0.0
        wins = sum(1 for p in profits if p > 0)
        win_rate = wins / n

        return sharpe, win_rate

    def _get_baseline(
        self, session: object, strategy_id: str,
    ) -> tuple[float | None, float | None]:
        """Get baseline Sharpe and win_rate from most recent backtest."""
        records = self.backtest_repo.get_history(session, strategy_id, limit=1)
        if not records:
            return None, None

        record = records[0]
        sharpe = record.sharpe_ratio

        win_rate = None
        try:
            result = json.loads(record.result_json)
            win_rate = result.get("win_rate")
        except (json.JSONDecodeError, TypeError):
            pass

        return sharpe, win_rate

    def _evaluate_strategy(
        self, session: object, strategy_id: str,
    ) -> PerformanceSnapshot:
        """Evaluate a single strategy: rolling metrics vs baseline."""
        snapshot = PerformanceSnapshot(strategy_id=strategy_id)

        # Fetch closed trades for this strategy
        trades = self.trade_repo.list_closed(
            session, strategy_name=strategy_id,
            limit=self.config.rolling_window_extended,
        )

        # Standard window metrics
        sharpe, win_rate = self._compute_rolling_metrics(
            trades, self.config.rolling_window,
        )
        snapshot.rolling_sharpe = sharpe
        snapshot.rolling_win_rate = win_rate

        # Baseline comparison
        b_sharpe, b_win_rate = self._get_baseline(session, strategy_id)
        snapshot.baseline_sharpe = b_sharpe
        snapshot.baseline_win_rate = b_win_rate

        # Degradation calculation
        if sharpe is not None and b_sharpe is not None and b_sharpe != 0:
            snapshot.degradation_pct_sharpe = (b_sharpe - sharpe) / abs(b_sharpe)

        if win_rate is not None and b_win_rate is not None and b_win_rate != 0:
            snapshot.degradation_pct_win_rate = (b_win_rate - win_rate) / abs(b_win_rate)

        # Alert level determination
        # CRITICAL: extended window Sharpe < critical_sharpe
        ext_sharpe, _ = self._compute_rolling_metrics(
            trades, self.config.rolling_window_extended,
        )
        if ext_sharpe is not None and ext_sharpe < self.config.critical_sharpe:
            snapshot.alert_level = "critical"
        # WARNING: degradation exceeds threshold
        elif (
            snapshot.degradation_pct_sharpe is not None
            and snapshot.degradation_pct_sharpe >= self.config.warning_threshold
        ) or (
            snapshot.degradation_pct_win_rate is not None
            and snapshot.degradation_pct_win_rate >= self.config.warning_threshold
        ):
            snapshot.alert_level = "warning"

        return snapshot

    # -- batch ---------------------------------------------------------------

    def check_all(self, session: object) -> list[PerformanceSnapshot]:
        """Evaluate all active strategies."""
        active = self.lifecycle.list_by_status("active")
        snapshots: list[PerformanceSnapshot] = []

        for entry in active:
            strategy_id = entry.get("id", "")
            try:
                snap = self._evaluate_strategy(session, strategy_id)
                snapshots.append(snap)

                if snap.alert_level == "critical":
                    self._handle_critical(strategy_id, snap)
                elif snap.alert_level == "warning":
                    self._handle_warning(strategy_id, snap)
            except Exception:
                logger.exception("Error evaluating strategy %s", strategy_id)

        return snapshots

    # -- alert handlers ------------------------------------------------------

    def _handle_critical(self, strategy_id: str, snap: PerformanceSnapshot) -> None:
        """Pause strategy and notify on critical degradation."""
        state = self.runtime_store.load()
        state.paused_strategies.add(strategy_id)
        self.runtime_store.save(state)

        self.notifier.send_performance_alert(snap)
        logger.warning(
            "Strategy %s auto-paused: rolling Sharpe %.3f < %.1f",
            strategy_id,
            snap.rolling_sharpe or 0.0,
            self.config.critical_sharpe,
        )

    def _handle_warning(self, strategy_id: str, snap: PerformanceSnapshot) -> None:
        """Notify on warning-level degradation (no pause)."""
        self.notifier.send_performance_alert(snap)
        logger.info("Strategy %s warning", strategy_id)

    # -- daemon --------------------------------------------------------------

    def run_daemon(self, session_factory: object | None = None) -> threading.Thread:
        """Start a daemon thread that periodically checks all strategies.

        *session_factory* should be a callable returning a context-managed
        SQLAlchemy session (e.g. ``SessionLocal``).
        """

        def _loop() -> None:
            while True:
                try:
                    if session_factory is not None:
                        with session_factory() as session:
                            self.check_all(session)
                    else:
                        self.check_all(None)
                except Exception:
                    logger.exception("Performance monitor cycle failed")
                time.sleep(self.config.check_interval_seconds)

        thread = threading.Thread(target=_loop, daemon=True, name="perf-monitor")
        thread.start()
        logger.info(
            "Performance monitor daemon started (interval=%ds)",
            self.config.check_interval_seconds,
        )
        return thread

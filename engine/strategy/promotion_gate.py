"""Promotion gate -- validates paper->live promotion criteria."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from engine.core.repository import PaperRepository, TradeRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config / Result models
# ---------------------------------------------------------------------------


class PromotionConfig(BaseModel):
    """Promotion gate thresholds. Merged from code defaults < global config < strategy override."""

    min_days: int = 7
    min_trades: int = 10
    min_sharpe: float = 0.3
    min_win_rate: float = 0.30
    max_drawdown: float = -0.20
    min_cumulative_pnl: float = 0.0


class PromotionCheck(BaseModel):
    """Single criterion check result."""

    name: str
    required: float
    actual: float | None
    passed: bool


class PromotionResult(BaseModel):
    """Aggregate promotion evaluation result."""

    passed: bool
    checks: dict[str, PromotionCheck]
    summary: str
    estimated_promotion: str | None = None


# ---------------------------------------------------------------------------
# Config resolution (3-level merge)
# ---------------------------------------------------------------------------


def resolve_promotion_config(
    strategy_def: "StrategyDefinition | None",
    global_config: dict,
) -> PromotionConfig:
    """Merge: code defaults -> global_config['promotion_gates'] -> strategy_def.promotion_gates."""
    merged: dict = {}

    # Layer 1: global config
    gates = global_config.get("promotion_gates", {})
    if gates:
        merged.update(gates)

    # Timeframe-based min_trades override
    if strategy_def is not None:
        tf = strategy_def.timeframes[0] if strategy_def.timeframes else None
        tf_map = global_config.get("timeframe_min_trades", {})
        if tf and tf in tf_map:
            merged["min_trades"] = tf_map[tf]

    # Layer 2: strategy-level override
    if strategy_def is not None and getattr(strategy_def, "promotion_gates", None):
        merged.update(strategy_def.promotion_gates)

    return PromotionConfig(**{k: v for k, v in merged.items() if k in PromotionConfig.model_fields})


# ---------------------------------------------------------------------------
# PromotionGate
# ---------------------------------------------------------------------------


class PromotionGate:
    """Evaluates whether a paper strategy meets promotion criteria."""

    def __init__(self, paper_repo: PaperRepository, trade_repo: TradeRepository) -> None:
        self.paper_repo = paper_repo
        self.trade_repo = trade_repo

    def evaluate(
        self, strategy_id: str, config: PromotionConfig, session: Session,
    ) -> PromotionResult:
        """Run all 6 checks and return PromotionResult."""
        checks: dict[str, PromotionCheck] = {}

        # Fetch data
        snapshots = self.paper_repo.get_daily_snapshots(session, strategy_id, limit=9999)
        snapshots.sort(key=lambda s: s.date)  # ascending
        trades = self.trade_repo.list_closed(
            session, strategy_name=strategy_id, broker="paper", limit=100000,
        )

        # 1. Days check
        if len(snapshots) >= 2:
            first_date = datetime.fromisoformat(snapshots[0].date).date()
            last_date = datetime.fromisoformat(snapshots[-1].date).date()
            actual_days = (last_date - first_date).days + 1
        elif len(snapshots) == 1:
            actual_days = 1
        else:
            actual_days = 0
        checks["days"] = PromotionCheck(
            name="운영 기간",
            required=config.min_days,
            actual=actual_days,
            passed=actual_days >= config.min_days,
        )

        # 2. Trade count
        trade_count = len(trades)
        checks["trades"] = PromotionCheck(
            name="거래 수",
            required=config.min_trades,
            actual=trade_count,
            passed=trade_count >= config.min_trades,
        )

        # 3. Win rate
        if trade_count > 0:
            wins = sum(1 for t in trades if (t.profit_abs or 0) > 0)
            win_rate = wins / trade_count
        else:
            win_rate = 0.0
        checks["win_rate"] = PromotionCheck(
            name="승률",
            required=config.min_win_rate,
            actual=round(win_rate, 4),
            passed=win_rate >= config.min_win_rate,
        )

        # 4. Sharpe ratio (annualized, from daily PnL)
        if len(snapshots) >= 2:
            daily_pnls = [s.daily_pnl for s in snapshots]
            mean_pnl = sum(daily_pnls) / len(daily_pnls)
            variance = sum((p - mean_pnl) ** 2 for p in daily_pnls) / len(daily_pnls)
            std_pnl = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_pnl / std_pnl * math.sqrt(365)) if std_pnl > 0 else None
        else:
            sharpe = None

        checks["sharpe"] = PromotionCheck(
            name="Sharpe Ratio",
            required=config.min_sharpe,
            actual=round(sharpe, 4) if sharpe is not None else None,
            passed=(sharpe is not None and sharpe >= config.min_sharpe) if sharpe is not None else True,
        )

        # 5. Max drawdown (peak-to-trough from equity curve)
        if len(snapshots) >= 2:
            equities = [s.equity for s in snapshots]
            peak = equities[0]
            max_dd = 0.0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (eq - peak) / peak if peak > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd
        else:
            max_dd = 0.0

        checks["max_drawdown"] = PromotionCheck(
            name="최대 낙폭",
            required=config.max_drawdown,
            actual=round(max_dd, 4),
            passed=max_dd >= config.max_drawdown,  # DD is negative; -0.10 >= -0.20 means OK
        )

        # 6. Cumulative PnL
        cum_pnl = snapshots[-1].cumulative_pnl if snapshots else 0.0
        checks["cumulative_pnl"] = PromotionCheck(
            name="누적 손익",
            required=config.min_cumulative_pnl,
            actual=round(cum_pnl, 2),
            passed=cum_pnl >= config.min_cumulative_pnl,
        )

        # Aggregate
        passed = all(c.passed for c in checks.values())
        failed_names = [c.name for c in checks.values() if not c.passed]
        summary = "모든 기준 충족" if passed else f"미충족: {', '.join(failed_names)}"

        estimated = self._estimate_promotion(checks, config, strategy_id, session) if not passed else None

        return PromotionResult(
            passed=passed,
            checks=checks,
            summary=summary,
            estimated_promotion=estimated,
        )

    def _estimate_promotion(
        self,
        checks: dict[str, PromotionCheck],
        config: PromotionConfig,
        strategy_id: str,
        session: Session,
    ) -> str | None:
        """Estimate when promotion might be possible."""
        parts: list[str] = []

        # Days estimate
        days_check = checks.get("days")
        if days_check and not days_check.passed and days_check.actual is not None:
            remaining = config.min_days - int(days_check.actual)
            if remaining > 0:
                parts.append(f"기간 {remaining}일 남음")

        # Trades estimate (based on recent 7-day trade rate)
        trades_check = checks.get("trades")
        if trades_check and not trades_check.passed and trades_check.actual is not None:
            remaining_trades = config.min_trades - int(trades_check.actual)
            if remaining_trades > 0:
                snapshots = self.paper_repo.get_daily_snapshots(session, strategy_id, limit=7)
                if snapshots:
                    recent_trades = sum(s.trade_count for s in snapshots)
                    days_count = len(snapshots)
                    daily_rate = recent_trades / days_count if days_count > 0 else 0
                    if daily_rate > 0:
                        est_days = math.ceil(remaining_trades / daily_rate)
                        parts.append(f"거래 {remaining_trades}건 부족, 약 {est_days}일 예상")
                    else:
                        parts.append(f"거래 {remaining_trades}건 부족")
                else:
                    parts.append(f"거래 {remaining_trades}건 부족")

        # Other checks: generic feedback
        for key in ("sharpe", "win_rate", "max_drawdown", "cumulative_pnl"):
            check = checks.get(key)
            if check and not check.passed:
                parts.append(f"{check.name} 현재 추세 유지 시 조건부")

        return "; ".join(parts) if parts else None

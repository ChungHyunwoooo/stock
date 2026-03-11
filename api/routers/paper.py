"""Paper trading performance REST API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_db
from engine.core.repository import PaperRepository, TradeRepository
from engine.strategy.promotion_gate import (
    PromotionCheck,
    PromotionConfig,
    PromotionGate,
    PromotionResult,
    resolve_promotion_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper", tags=["paper"])
_paper_repo = PaperRepository()
_trade_repo = TradeRepository()


def _load_global_config() -> dict:
    try:
        path = Path("config/paper_trading.json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PaperStatusItem(BaseModel):
    strategy_id: str
    start_date: str
    days: int
    trades: int
    win_rate: float | None
    cumulative_pnl: float
    sharpe: float | None
    max_drawdown: float | None
    readiness: str
    passed: bool


class PaperStatusResponse(BaseModel):
    strategies: list[PaperStatusItem]


class PromotionCheckResponse(BaseModel):
    name: str
    required: float
    actual: float | None
    passed: bool


class PromotionReadinessResponse(BaseModel):
    strategy_id: str
    passed: bool
    summary: str
    estimated_promotion: str | None
    checks: dict[str, PromotionCheckResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=PaperStatusResponse)
def paper_status(
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> dict:
    """All paper strategies performance summary."""
    gate = PromotionGate(paper_repo=_paper_repo, trade_repo=_trade_repo)
    global_config = _load_global_config()
    config = resolve_promotion_config(None, global_config)

    strategy_ids = _paper_repo.get_paper_strategies(db)
    items: list[dict] = []

    for sid in strategy_ids:
        result = gate.evaluate(sid, config, db)
        snapshots = _paper_repo.get_daily_snapshots(db, sid, limit=9999)
        snapshots.sort(key=lambda s: s.date)

        checks = result.checks
        passed_count = sum(1 for c in checks.values() if c.passed)

        items.append({
            "strategy_id": sid,
            "start_date": snapshots[0].date if snapshots else "-",
            "days": len(snapshots),
            "trades": int(checks["trades"].actual) if checks.get("trades") and checks["trades"].actual is not None else 0,
            "win_rate": checks["win_rate"].actual if checks.get("win_rate") else None,
            "cumulative_pnl": checks["cumulative_pnl"].actual if checks.get("cumulative_pnl") and checks["cumulative_pnl"].actual is not None else 0.0,
            "sharpe": checks["sharpe"].actual if checks.get("sharpe") else None,
            "max_drawdown": checks["max_drawdown"].actual if checks.get("max_drawdown") else None,
            "readiness": f"{passed_count}/{len(checks)}",
            "passed": result.passed,
        })

    return {"strategies": items}


@router.get("/status/{strategy_id}", response_model=PaperStatusItem)
def paper_status_detail(
    strategy_id: str,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> dict:
    """Single strategy paper performance detail."""
    gate = PromotionGate(paper_repo=_paper_repo, trade_repo=_trade_repo)
    global_config = _load_global_config()
    config = resolve_promotion_config(None, global_config)

    snapshots = _paper_repo.get_daily_snapshots(db, strategy_id, limit=9999)
    if not snapshots:
        raise HTTPException(status_code=404, detail=f"Paper data not found: {strategy_id}")

    snapshots.sort(key=lambda s: s.date)
    result = gate.evaluate(strategy_id, config, db)
    checks = result.checks
    passed_count = sum(1 for c in checks.values() if c.passed)

    return {
        "strategy_id": strategy_id,
        "start_date": snapshots[0].date,
        "days": len(snapshots),
        "trades": int(checks["trades"].actual) if checks.get("trades") and checks["trades"].actual is not None else 0,
        "win_rate": checks["win_rate"].actual if checks.get("win_rate") else None,
        "cumulative_pnl": checks["cumulative_pnl"].actual if checks.get("cumulative_pnl") and checks["cumulative_pnl"].actual is not None else 0.0,
        "sharpe": checks["sharpe"].actual if checks.get("sharpe") else None,
        "max_drawdown": checks["max_drawdown"].actual if checks.get("max_drawdown") else None,
        "readiness": f"{passed_count}/{len(checks)}",
        "passed": result.passed,
    }


@router.get("/promotion/{strategy_id}", response_model=PromotionReadinessResponse)
def promotion_readiness(
    strategy_id: str,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> dict:
    """Promotion criteria check for a strategy."""
    gate = PromotionGate(paper_repo=_paper_repo, trade_repo=_trade_repo)
    global_config = _load_global_config()
    config = resolve_promotion_config(None, global_config)

    result = gate.evaluate(strategy_id, config, db)

    return {
        "strategy_id": strategy_id,
        "passed": result.passed,
        "summary": result.summary,
        "estimated_promotion": result.estimated_promotion,
        "checks": {
            k: {"name": v.name, "required": v.required, "actual": v.actual, "passed": v.passed}
            for k, v in result.checks.items()
        },
    }

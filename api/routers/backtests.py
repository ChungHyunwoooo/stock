from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db
from api.routers.symbols import get_symbol_name, get_symbols_by_market
from engine.backtest.runner import BacktestRunner
from engine.schema import StrategyDefinition
from engine.store.models import BacktestRecord
from engine.store.repository import BacktestRepository, StrategyRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtests", tags=["backtests"])
_repo = BacktestRepository()
_s_repo = StrategyRepository()


class BacktestRunRequest(BaseModel):
    strategy_id: int | None = None
    strategy: StrategyDefinition | None = None
    symbol: str
    start: str
    end: str
    timeframe: str = "1d"
    initial_capital: float = 10_000.0
    save: bool = True
    regime_enabled: bool = False


class BacktestResponse(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    total_return: float
    sharpe_ratio: float | None
    max_drawdown: float | None
    result_json: str
    created_at: str | None

    @classmethod
    def from_record(cls, r: BacktestRecord) -> BacktestResponse:
        return cls(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date,
            end_date=r.end_date,
            total_return=r.total_return,
            sharpe_ratio=r.sharpe_ratio,
            max_drawdown=r.max_drawdown,
            result_json=r.result_json,
            created_at=str(r.created_at)[:19] if r.created_at else None,
        )


@router.post("/run", response_model=BacktestResponse, status_code=201)
def run_backtest(
    body: BacktestRunRequest,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> BacktestResponse:
    # Resolve strategy
    if body.strategy is not None:
        strategy = body.strategy
        s_record = _s_repo.save(db, strategy)
    elif body.strategy_id is not None:
        s_record = _s_repo.get(db, body.strategy_id)
        if s_record is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        import json
        strategy = StrategyDefinition.model_validate(json.loads(s_record.definition_json))
    else:
        raise HTTPException(status_code=422, detail="Provide either strategy_id or strategy body")

    runner = BacktestRunner()
    result = runner.run(strategy, body.symbol, body.start, body.end, body.timeframe, body.initial_capital, regime_enabled=body.regime_enabled)

    record = BacktestRecord(
        strategy_id=s_record.id,
        symbol=result.symbol,
        timeframe=result.timeframe,
        start_date=result.start_date,
        end_date=result.end_date,
        total_return=result.total_return,
        sharpe_ratio=result.sharpe_ratio,
        max_drawdown=result.max_drawdown,
        result_json=result.to_result_json(),
    )
    if body.save:
        _repo.save(db, record)

    return BacktestResponse.from_record(record)


@router.get("", response_model=list[BacktestResponse])
def list_backtests(
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> list[BacktestResponse]:
    records = _repo.list_all(db)
    return [BacktestResponse.from_record(r) for r in records]


@router.get("/{backtest_id}", response_model=BacktestResponse)
def get_backtest(
    backtest_id: int,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> BacktestResponse:
    record = _repo.get(db, backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return BacktestResponse.from_record(record)


@router.get("/strategy/{strategy_id}", response_model=list[BacktestResponse])
def get_by_strategy(
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> list[BacktestResponse]:
    records = _repo.get_by_strategy(db, strategy_id)
    return [BacktestResponse.from_record(r) for r in records]


# ---------------------------------------------------------------------------
# Multi-symbol scan
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    strategy_id: int | None = None
    strategy: StrategyDefinition | None = None
    market: str = "kr_stock"
    symbols: list[str] | None = None  # optional subset; None = full market
    start: str
    end: str
    timeframe: str = "1d"
    initial_capital: float = 10_000.0
    top_n: int = 10


class ScanResultItem(BaseModel):
    symbol: str
    name: str
    total_return: float
    sharpe_ratio: float | None
    max_drawdown: float | None
    num_trades: int


class ScanResponse(BaseModel):
    total_scanned: int
    total_success: int
    total_failed: int
    best: list[ScanResultItem]
    worst: list[ScanResultItem]


def _run_single_backtest(
    runner: BacktestRunner,
    strategy: StrategyDefinition,
    symbol: str,
    start: str,
    end: str,
    timeframe: str,
    initial_capital: float,
    market: str,
) -> ScanResultItem | None:
    """Run one backtest, return None on failure."""
    try:
        result = runner.run(strategy, symbol, start, end, timeframe, initial_capital)
        return ScanResultItem(
            symbol=symbol,
            name=get_symbol_name(symbol, market),
            total_return=round(result.total_return * 100, 2),
            sharpe_ratio=round(result.sharpe_ratio, 4) if result.sharpe_ratio is not None else None,
            max_drawdown=round(result.max_drawdown * 100, 2) if result.max_drawdown is not None else None,
            num_trades=len(result.trades),
        )
    except Exception as e:
        logger.debug("Scan backtest failed for %s: %s", symbol, e)
        return None


@router.post("/scan", response_model=ScanResponse)
def scan_symbols(
    body: ScanRequest,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    # Resolve strategy
    if body.strategy is not None:
        strategy = body.strategy
    elif body.strategy_id is not None:
        s_record = _s_repo.get(db, body.strategy_id)
        if s_record is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy = StrategyDefinition.model_validate(json.loads(s_record.definition_json))
    else:
        raise HTTPException(status_code=422, detail="Provide either strategy_id or strategy body")

    # Resolve symbol list
    if body.symbols:
        symbol_list = body.symbols
    else:
        cached = get_symbols_by_market(body.market)
        symbol_list = [s["symbol"] for s in cached]

    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols found for this market")

    runner = BacktestRunner()
    results: list[ScanResultItem] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(
                _run_single_backtest,
                runner, strategy, sym,
                body.start, body.end, body.timeframe,
                body.initial_capital, body.market,
            ): sym
            for sym in symbol_list
        }
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                results.append(item)
            else:
                failed += 1

    # Sort by total_return
    results.sort(key=lambda x: x.total_return, reverse=True)

    top_n = body.top_n
    best = results[:top_n]
    worst = list(reversed(results[-top_n:])) if len(results) >= top_n else list(reversed(results))

    return {
        "total_scanned": len(symbol_list),
        "total_success": len(results),
        "total_failed": failed,
        "best": best,
        "worst": worst,
    }

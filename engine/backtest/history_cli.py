"""CLI for backtest history -- rich table display, comparison, deletion."""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.table import Table

from engine.core.database import get_session
from engine.core.repository import BacktestRepository

logger = logging.getLogger(__name__)
_repo = BacktestRepository()


def show_history(strategy_id: int, limit: int = 20) -> list[dict]:
    """Display backtest history for a strategy as a rich table.

    Returns list[dict] for testability.
    """
    with get_session() as session:
        records = _repo.get_history(session, strategy_id, limit=limit)

    rows: list[dict] = []
    for r in records:
        rows.append({
            "id": r.id,
            "strategy_id": r.strategy_id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "total_return": r.total_return,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "slippage_model": r.slippage_model or "none",
            "fee_rate": r.fee_rate or 0.0,
            "wf_result": r.wf_result or "-",
            "created_at": str(r.created_at)[:19] if r.created_at else "-",
        })

    table = Table(title=f"Backtest History -- Strategy {strategy_id}")
    table.add_column("ID", justify="right")
    table.add_column("Date", style="dim")
    table.add_column("Symbol")
    table.add_column("Return", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("Slippage")
    table.add_column("Fee", justify="right")
    table.add_column("WF", justify="center")

    for row in rows:
        table.add_row(
            str(row["id"]),
            row["created_at"],
            row["symbol"],
            f"{row['total_return']:.4f}",
            f"{row['sharpe_ratio']:.4f}" if row["sharpe_ratio"] is not None else "-",
            f"{row['max_drawdown']:.4f}" if row["max_drawdown"] is not None else "-",
            row["slippage_model"],
            f"{row['fee_rate']:.4f}",
            row["wf_result"],
        )

    Console().print(table)
    return rows


def compare_strategies(strategy_ids: list[int]) -> list[dict]:
    """Display cross-strategy comparison as a rich table.

    Returns list[dict] for testability.
    """
    with get_session() as session:
        records = _repo.compare_strategies(session, strategy_ids)

    rows: list[dict] = []
    for r in records:
        rows.append({
            "id": r.id,
            "strategy_id": r.strategy_id,
            "symbol": r.symbol,
            "total_return": r.total_return,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "slippage_model": r.slippage_model or "none",
            "fee_rate": r.fee_rate or 0.0,
            "wf_result": r.wf_result or "-",
            "created_at": str(r.created_at)[:19] if r.created_at else "-",
        })

    table = Table(title="Strategy Comparison")
    table.add_column("Strategy", justify="right")
    table.add_column("ID", justify="right")
    table.add_column("Symbol")
    table.add_column("Date", style="dim")
    table.add_column("Return", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("WF", justify="center")

    for row in rows:
        table.add_row(
            str(row["strategy_id"]),
            str(row["id"]),
            row["symbol"],
            row["created_at"],
            f"{row['total_return']:.4f}",
            f"{row['sharpe_ratio']:.4f}" if row["sharpe_ratio"] is not None else "-",
            f"{row['max_drawdown']:.4f}" if row["max_drawdown"] is not None else "-",
            row["wf_result"],
        )

    Console().print(table)
    return rows


def delete_history(
    strategy_id: int | None = None, backtest_id: int | None = None
) -> None:
    """Delete backtest records by strategy or individual ID."""
    with get_session() as session:
        if backtest_id is not None:
            _repo.delete(session, backtest_id)
            logger.info("Deleted backtest record %d", backtest_id)
        elif strategy_id is not None:
            _repo.delete_by_strategy(session, strategy_id)
            logger.info("Deleted all backtest records for strategy %d", strategy_id)
        else:
            logger.warning("No strategy_id or backtest_id provided")


def main() -> None:
    """CLI entry point for backtest history management."""
    parser = argparse.ArgumentParser(description="Backtest history management")
    parser.add_argument("--strategy-id", type=int, help="Strategy ID for history/delete")
    parser.add_argument("--compare", type=str, help="Comma-separated strategy IDs to compare")
    parser.add_argument("--limit", type=int, default=20, help="Max records (default 20)")
    parser.add_argument("--delete", action="store_true", help="Delete mode")
    parser.add_argument("--backtest-id", type=int, help="Single backtest ID to delete")

    args = parser.parse_args()

    if args.compare:
        ids = [int(x.strip()) for x in args.compare.split(",") if x.strip()]
        compare_strategies(ids)
    elif args.delete:
        delete_history(strategy_id=args.strategy_id, backtest_id=args.backtest_id)
    elif args.strategy_id:
        show_history(args.strategy_id, limit=args.limit)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

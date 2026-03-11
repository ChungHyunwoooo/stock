"""CLI for paper trading performance -- rich table display and promotion readiness."""

from __future__ import annotations

import json
import logging
import math

from rich.console import Console
from rich.table import Table

from engine.core.database import get_session
from engine.core.repository import PaperRepository, TradeRepository
from engine.strategy.promotion_gate import (
    PromotionConfig,
    PromotionGate,
    PromotionResult,
    resolve_promotion_config,
)

logger = logging.getLogger(__name__)
_paper_repo = PaperRepository()
_trade_repo = TradeRepository()


def _load_global_config() -> dict:
    """Load paper_trading.json config."""
    try:
        from pathlib import Path
        path = Path("config/paper_trading.json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def show_paper_status(strategy_id: str | None = None) -> list[dict]:
    """Display paper strategy performance as a rich table.

    Returns list[dict] for testability.
    """
    gate = PromotionGate(paper_repo=_paper_repo, trade_repo=_trade_repo)
    global_config = _load_global_config()
    config = resolve_promotion_config(None, global_config)

    with get_session() as session:
        if strategy_id:
            strategy_ids = [strategy_id]
        else:
            strategy_ids = _paper_repo.get_paper_strategies(session)

        rows: list[dict] = []
        for sid in strategy_ids:
            result = gate.evaluate(sid, config, session)
            snapshots = _paper_repo.get_daily_snapshots(session, sid, limit=9999)
            snapshots.sort(key=lambda s: s.date)

            start_date = snapshots[0].date if snapshots else "-"
            days = len(snapshots)
            trades = result.checks.get("trades")
            win_rate = result.checks.get("win_rate")
            sharpe = result.checks.get("sharpe")
            dd = result.checks.get("max_drawdown")
            pnl = result.checks.get("cumulative_pnl")

            passed_count = sum(1 for c in result.checks.values() if c.passed)
            total_count = len(result.checks)

            rows.append({
                "strategy_id": sid,
                "start_date": start_date,
                "days": days,
                "trades": int(trades.actual) if trades and trades.actual is not None else 0,
                "win_rate": f"{win_rate.actual:.1%}" if win_rate and win_rate.actual is not None else "-",
                "cumulative_pnl": pnl.actual if pnl and pnl.actual is not None else 0.0,
                "sharpe": f"{sharpe.actual:.2f}" if sharpe and sharpe.actual is not None else "-",
                "max_dd": f"{dd.actual:.1%}" if dd and dd.actual is not None else "-",
                "readiness": f"{passed_count}/{total_count}",
                "passed": result.passed,
            })

    table = Table(title="Paper Trading Status")
    table.add_column("Strategy", style="cyan")
    table.add_column("Start", style="dim")
    table.add_column("Days", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("Ready", justify="center")

    for row in rows:
        ready_style = "green" if row["passed"] else "red"
        table.add_row(
            row["strategy_id"],
            row["start_date"],
            str(row["days"]),
            str(row["trades"]),
            row["win_rate"],
            f"{row['cumulative_pnl']:.0f}",
            row["sharpe"],
            row["max_dd"],
            f"[{ready_style}]{row['readiness']}[/{ready_style}]",
        )

    Console().print(table)
    return rows


def show_paper_detail(strategy_id: str) -> dict:
    """Display detailed paper performance for a single strategy."""
    with get_session() as session:
        snapshots = _paper_repo.get_daily_snapshots(session, strategy_id, limit=9999)
        snapshots.sort(key=lambda s: s.date)
        trades = _trade_repo.list_closed(session, strategy_name=strategy_id, broker="paper", limit=100000)

    # Symbol breakdown
    symbol_stats: dict[str, dict] = {}
    for t in trades:
        sym = t.symbol
        if sym not in symbol_stats:
            symbol_stats[sym] = {"count": 0, "wins": 0, "pnl": 0.0}
        symbol_stats[sym]["count"] += 1
        if (t.profit_abs or 0) > 0:
            symbol_stats[sym]["wins"] += 1
        symbol_stats[sym]["pnl"] += t.profit_abs or 0

    detail = {
        "strategy_id": strategy_id,
        "total_days": len(snapshots),
        "total_trades": len(trades),
        "symbol_breakdown": symbol_stats,
        "daily_pnl": [{"date": s.date, "pnl": s.daily_pnl, "equity": s.equity} for s in snapshots],
    }

    # Symbol table
    sym_table = Table(title=f"Paper Detail -- {strategy_id} (Symbol Breakdown)")
    sym_table.add_column("Symbol")
    sym_table.add_column("Trades", justify="right")
    sym_table.add_column("Wins", justify="right")
    sym_table.add_column("Win%", justify="right")
    sym_table.add_column("PnL", justify="right")

    for sym, stats in sorted(symbol_stats.items()):
        wr = f"{stats['wins'] / stats['count']:.1%}" if stats["count"] > 0 else "-"
        sym_table.add_row(sym, str(stats["count"]), str(stats["wins"]), wr, f"{stats['pnl']:.0f}")

    Console().print(sym_table)

    # Daily PnL table
    pnl_table = Table(title=f"Daily PnL -- {strategy_id}")
    pnl_table.add_column("Date", style="dim")
    pnl_table.add_column("Daily PnL", justify="right")
    pnl_table.add_column("Equity", justify="right")

    for s in snapshots[-20:]:  # last 20 days
        style = "green" if s.daily_pnl >= 0 else "red"
        pnl_table.add_row(s.date, f"[{style}]{s.daily_pnl:.0f}[/{style}]", f"{s.equity:.0f}")

    Console().print(pnl_table)
    return detail


def show_promotion_readiness(strategy_id: str) -> PromotionResult:
    """Display promotion criteria status as a rich table."""
    gate = PromotionGate(paper_repo=_paper_repo, trade_repo=_trade_repo)
    global_config = _load_global_config()
    config = resolve_promotion_config(None, global_config)

    with get_session() as session:
        result = gate.evaluate(strategy_id, config, session)

    table = Table(title=f"Promotion Readiness -- {strategy_id}")
    table.add_column("Criterion")
    table.add_column("Required", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Status", justify="center")

    for check in result.checks.values():
        status = "[green]OK[/green]" if check.passed else "[red]NG[/red]"
        actual_str = f"{check.actual}" if check.actual is not None else "N/A (skip)"
        table.add_row(check.name, f"{check.required}", actual_str, status)

    Console().print(table)

    if result.estimated_promotion:
        Console().print(f"\n[yellow]예상 승격 시점:[/yellow] {result.estimated_promotion}")

    if result.passed:
        Console().print("\n[green bold]모든 기준 충족 -- 승격 가능[/green bold]")
    else:
        Console().print(f"\n[red]{result.summary}[/red]")

    return result

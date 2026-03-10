"""CLI entry point for the Trading Strategy Engine (tse)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="tse", help="Trading Strategy Engine CLI", no_args_is_help=True)
strategy_app = typer.Typer(help="Strategy management commands", no_args_is_help=True)
strategies_app = typer.Typer(help="Strategy management", no_args_is_help=True)
backtest_app = typer.Typer(help="Backtesting commands", no_args_is_help=True)
knowledge_app = typer.Typer(help="Knowledge base commands", no_args_is_help=True)
runtime_app = typer.Typer(help="Trading runtime controls", no_args_is_help=True)

app.add_typer(strategy_app, name="strategy")
app.add_typer(strategies_app, name="strategies")
app.add_typer(backtest_app, name="bt")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(runtime_app, name="runtime")

console = Console()

def _print_runtime_state(state) -> None:
    pending = [p for p in state.pending_orders if p.state.value == "pending"]
    open_positions = [p for p in state.positions if p.status.value == "open"]
    console.print(f"mode            : {state.mode.value}")
    console.print(f"paused          : {state.paused}")
    console.print(f"automation      : {state.automation_enabled}")
    console.print(f"broker          : {state.broker.value}")
    console.print(f"pending orders  : {len(pending)}")
    console.print(f"open positions  : {len(open_positions)}")
    console.print(f"executions      : {len(state.executions)}")
    console.print(f"updated at      : {state.updated_at}")

# ---------------------------------------------------------------------------
# Strategy commands
# ---------------------------------------------------------------------------

@strategy_app.command("validate")
def strategy_validate(
    path: Path = typer.Argument(..., help="Path to strategy JSON file"),
) -> None:
    """Validate a strategy JSON file against the schema."""
    from engine.schema import StrategyDefinition

    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)

    try:
        data = json.loads(path.read_text())
        strategy = StrategyDefinition.model_validate(data)
        console.print(f"[green]✓ Valid[/green] strategy: [bold]{strategy.name}[/bold] v{strategy.version}")
    except Exception as exc:
        console.print(f"[red]✗ Invalid:[/red] {exc}")
        raise typer.Exit(1)

@strategy_app.command("show")
def strategy_show(
    path: Path = typer.Argument(..., help="Path to strategy JSON file"),
) -> None:
    """Show strategy details from a JSON file."""
    from engine.schema import StrategyDefinition

    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)

    data = json.loads(path.read_text())
    strategy = StrategyDefinition.model_validate(data)

    console.print(f"\n[bold]{strategy.name}[/bold] v{strategy.version}  [{strategy.status.value}]")
    console.print(f"  Description : {strategy.description or '—'}")
    console.print(f"  Markets     : {', '.join(m.value for m in strategy.markets)}")
    console.print(f"  Direction   : {strategy.direction.value}")
    console.print(f"  Timeframes  : {', '.join(strategy.timeframes)}")
    console.print(f"  Indicators  : {', '.join(i.name for i in strategy.indicators)}")
    console.print(f"  Tags        : {', '.join(strategy.metadata.tags) or '—'}")
    console.print()

@strategy_app.command("list")
def strategy_list(
    db_url: str = typer.Option("sqlite:///tse.db", "--db", help="Database URL"),
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    """List all strategies stored in the database."""
    from engine.core.repository import StrategyRepository
    from engine.core.database import get_session, get_engine, init_db

    get_engine(db_url)
    init_db(db_url)
    repo = StrategyRepository()

    with get_session() as session:
        records = repo.list_all(session, status=status)

    if not records:
        console.print("[yellow]No strategies found.[/yellow]")
        return

    table = Table(title="Strategies")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Created")

    for r in records:
        table.add_row(
            str(r.id),
            r.name,
            r.version,
            r.status,
            str(r.created_at)[:10] if r.created_at else "—",
        )

    console.print(table)

# ---------------------------------------------------------------------------
# Backtest commands
# ---------------------------------------------------------------------------

@backtest_app.command("run")
def backtest_run(
    strategy_path: Path = typer.Argument(..., help="Path to strategy JSON file"),
    symbol: str = typer.Option(..., "--symbol", "-s", help="Ticker symbol"),
    start: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
    timeframe: str = typer.Option("1d", "--timeframe", "-t", help="Bar timeframe"),
    capital: float = typer.Option(10_000.0, "--capital", "-c", help="Initial capital"),
    save: bool = typer.Option(False, "--save", help="Save result to database"),
    db_url: str = typer.Option("sqlite:///tse.db", "--db", help="Database URL"),
) -> None:
    """Run a backtest for a strategy on a symbol."""
    from engine.backtest import BacktestRunner
    from engine.schema import StrategyDefinition

    if not strategy_path.exists():
        console.print(f"[red]File not found:[/red] {strategy_path}")
        raise typer.Exit(1)

    data = json.loads(strategy_path.read_text())
    strategy = StrategyDefinition.model_validate(data)

    console.print(f"Running backtest: [bold]{strategy.name}[/bold] on {symbol} [{start} → {end}]")

    runner = BacktestRunner()
    result = runner.run(strategy, symbol, start, end, timeframe, capital)

    console.print(f"\n[bold]Results[/bold]")
    console.print(f"  Total Return  : {result.total_return:+.2%}")
    console.print(f"  Sharpe Ratio  : {result.sharpe_ratio:.3f}" if result.sharpe_ratio is not None else "  Sharpe Ratio  : —")
    console.print(f"  Max Drawdown  : {result.max_drawdown:.2%}" if result.max_drawdown is not None else "  Max Drawdown  : —")
    console.print(f"  # Trades      : {len(result.trades)}")
    console.print(f"  Final Capital : {result.final_capital:,.2f}")

    if save:
        from engine.core.repository import BacktestRepository, StrategyRepository
        from engine.core.database import get_engine, get_session, init_db
        from engine.core.db_models import BacktestRecord

        get_engine(db_url)
        init_db(db_url)

        with get_session() as session:
            s_repo = StrategyRepository()
            s_record = s_repo.save(session, strategy)

            b_repo = BacktestRepository()
            b_record = BacktestRecord(
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
            b_repo.save(session, b_record)

        console.print("\n[green]✓ Result saved to database.[/green]")

# ---------------------------------------------------------------------------
# Knowledge commands
# ---------------------------------------------------------------------------

@knowledge_app.command("list")
def knowledge_list(
    base_dir: str = typer.Option("strategies/knowledge", "--dir", help="Knowledge base directory"),
    tag: str | None = typer.Option(None, "--tag", help="Filter by tag"),
    category: str | None = typer.Option(None, "--category", help="Filter by category"),
    query: str | None = typer.Option(None, "--query", "-q", help="Filter by title substring"),
) -> None:
    """List knowledge base entries."""
    from engine.core.knowledge_store import KnowledgeStore

    store = KnowledgeStore(base_dir)
    tags = [tag] if tag else None
    entries = store.search(query=query, tags=tags, category=category)

    if not entries:
        console.print("[yellow]No entries found.[/yellow]")
        return

    table = Table(title="Knowledge Base")
    table.add_column("Title")
    table.add_column("Category")
    table.add_column("Tags")
    table.add_column("Path", style="dim")

    for e in entries:
        table.add_row(e.title, e.category or "—", ", ".join(e.tags) or "—", e.path)

    console.print(table)

@knowledge_app.command("search")
def knowledge_search(
    query: str = typer.Argument(..., help="Search query (title substring)"),
    base_dir: str = typer.Option("strategies/knowledge", "--dir", help="Knowledge base directory"),
) -> None:
    """Search knowledge base by title."""
    from engine.core.knowledge_store import KnowledgeStore

    store = KnowledgeStore(base_dir)
    entries = store.search(query=query)

    if not entries:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    for e in entries:
        console.print(f"[bold]{e.title}[/bold]  [{e.category}]")
        if e.tags:
            console.print(f"  tags: {', '.join(e.tags)}")
        console.print(f"  {e.path}")
        console.print()

# ---------------------------------------------------------------------------
# Top-level: backtest (spec-compatible flat command)
# ---------------------------------------------------------------------------

@app.command()
def backtest(
    strategy: str = typer.Option(..., "--strategy", "-s", help="Path to strategy JSON"),
    symbol: str = typer.Option(..., "--symbol", help="Ticker symbol"),
    start: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
    capital: float = typer.Option(100_000.0, "--capital", "-c", help="Initial capital"),
    report: bool = typer.Option(False, "--report", "-r", help="Generate HTML report"),
) -> None:
    """Run backtest on a strategy."""
    from rich.panel import Panel

    from engine.backtest.runner import BacktestRunner
    from engine.schema import StrategyDefinition

    strategy_path = Path(strategy)
    if not strategy_path.exists():
        console.print(f"[red]Error: Strategy file not found: {strategy}[/red]")
        raise typer.Exit(1)

    try:
        strategy_def = StrategyDefinition.model_validate_json(strategy_path.read_text())
    except Exception as exc:
        console.print(f"[red]Error: Invalid strategy JSON — {exc}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]{strategy_def.name}[/bold] v{strategy_def.version}\n"
            f"Symbol: [cyan]{symbol}[/cyan]  |  {start} → {end}  |  Capital: {capital:,.0f}",
            title="[bold blue]Backtest[/bold blue]",
        )
    )

    try:
        runner = BacktestRunner()
        result = runner.run(
            strategy=strategy_def,
            symbol=symbol,
            start=start,
            end=end,
            initial_capital=capital,
        )
    except Exception as exc:
        console.print(f"[red]Error running backtest: {exc}[/red]")
        raise typer.Exit(1)

    summary = Table(title="Backtest Results", header_style="bold magenta")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")

    ret_color = "green" if result.total_return >= 0 else "red"
    summary.add_row("Initial Capital", f"{result.initial_capital:,.2f}")
    summary.add_row("Final Capital", f"{result.final_capital:,.2f}")
    summary.add_row("Total Return", f"[{ret_color}]{result.total_return:.2%}[/{ret_color}]")
    summary.add_row(
        "Sharpe Ratio",
        f"{result.sharpe_ratio:.3f}" if result.sharpe_ratio is not None else "N/A",
    )
    summary.add_row(
        "Max Drawdown",
        f"[red]{result.max_drawdown:.2%}[/red]" if result.max_drawdown is not None else "N/A",
    )
    summary.add_row("Num Trades", str(len(result.trades)))
    console.print(summary)

    if report:
        _generate_html_report(result, strategy_def.name, symbol)

    if result.trades:
        trades_table = Table(title="Trade Log", header_style="bold cyan")
        trades_table.add_column("Entry Date")
        trades_table.add_column("Exit Date")
        trades_table.add_column("Entry Price", justify="right")
        trades_table.add_column("Exit Price", justify="right")
        trades_table.add_column("PnL %", justify="right")
        for t in result.trades:
            color = "green" if t.pnl_pct >= 0 else "red"
            trades_table.add_row(
                t.entry_date, t.exit_date,
                f"{t.entry_price:,.4f}", f"{t.exit_price:,.4f}",
                f"[{color}]{t.pnl_pct:.2%}[/{color}]",
            )
        console.print(trades_table)

def _generate_html_report(result: object, strategy_name: str, symbol: str) -> None:
    """Write a minimal HTML report for BacktestResult."""
    from engine.backtest.runner import BacktestResult
    assert isinstance(result, BacktestResult)

    output_path = Path(f"report_{strategy_name}_{symbol}.html".replace("/", "_"))
    trades_rows = "".join(
        f"<tr><td>{t.entry_date}</td><td>{t.exit_date}</td>"
        f"<td>{t.entry_price:.4f}</td><td>{t.exit_price:.4f}</td>"
        f"<td style='color:{'green' if t.pnl_pct >= 0 else 'red'}'>{t.pnl_pct:.2%}</td></tr>"
        for t in result.trades
    )
    html = (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Backtest: {strategy_name}</title>"
        f"<style>body{{font-family:sans-serif;padding:2em}}"
        f"table{{border-collapse:collapse;width:100%}}"
        f"th,td{{border:1px solid #ccc;padding:8px}}th{{background:#eef}}</style></head><body>"
        f"<h1>Backtest: {strategy_name} — {symbol}</h1>"
        f"<table><tr><th>Metric</th><th>Value</th></tr>"
        f"<tr><td>Initial Capital</td><td>{result.initial_capital:,.2f}</td></tr>"
        f"<tr><td>Final Capital</td><td>{result.final_capital:,.2f}</td></tr>"
        f"<tr><td>Total Return</td><td>{result.total_return:.2%}</td></tr>"
        f"<tr><td>Sharpe</td><td>"
        f"{result.sharpe_ratio:.3f if result.sharpe_ratio is not None else 'N/A'}</td></tr>"
        f"<tr><td>Max Drawdown</td><td>"
        f"{result.max_drawdown:.2% if result.max_drawdown is not None else 'N/A'}</td></tr>"
        f"<tr><td>Trades</td><td>{len(result.trades)}</td></tr></table>"
        f"<h2>Trades</h2><table>"
        f"<tr><th>Entry</th><th>Exit</th><th>Entry $</th><th>Exit $</th><th>PnL</th></tr>"
        f"{trades_rows}</table></body></html>"
    )
    output_path.write_text(html)
    console.print(f"[green]Report written to {output_path}[/green]")

# ---------------------------------------------------------------------------
# Top-level: search (spec-compatible flat command)
# ---------------------------------------------------------------------------

@app.command()
def search(
    tag: list[str] = typer.Option([], "--tag", "-t", help="Filter by tag (repeatable)"),
    category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
    query: str = typer.Option(None, "--query", "-q", help="Title substring search"),
) -> None:
    """Search knowledge base."""
    from engine.core.knowledge_store import KnowledgeStore

    store = KnowledgeStore()
    results = store.search(query=query or None, tags=list(tag) if tag else None, category=category)

    if not results:
        console.print("[yellow]No entries found.[/yellow]")
        return

    tbl = Table(title=f"Knowledge Base ({len(results)} results)", header_style="bold magenta")
    tbl.add_column("Title", style="bold")
    tbl.add_column("Category")
    tbl.add_column("Tags")
    tbl.add_column("Source")
    tbl.add_column("Summary")
    for e in results:
        tbl.add_row(
            e.title, e.category or "",
            ", ".join(e.tags), e.source or "",
            (e.summary[:60] + "…") if len(e.summary) > 60 else e.summary,
        )
    console.print(tbl)

# ---------------------------------------------------------------------------
# strategies sub-commands (plural, directory-based)
# ---------------------------------------------------------------------------

@strategies_app.command("list")
def strategies_list(
    status: str = typer.Option(None, "--status", help="Filter by status"),
    directory: str = typer.Option("strategies", "--dir", "-d", help="Directory to scan"),
) -> None:
    """List all strategies from a directory of JSON files."""
    from engine.schema import StrategyDefinition

    base = Path(directory)
    if not base.exists():
        console.print(f"[red]Error: Directory not found: {directory}[/red]")
        raise typer.Exit(1)

    json_files = sorted(base.rglob("*.json"))
    if not json_files:
        console.print(f"[yellow]No JSON files found in {directory}.[/yellow]")
        return

    tbl = Table(title=f"Strategies in {directory}", header_style="bold magenta")
    tbl.add_column("Name", style="bold")
    tbl.add_column("Version")
    tbl.add_column("Status")
    tbl.add_column("Markets")
    tbl.add_column("Tags")
    tbl.add_column("File", style="dim")

    count = 0
    for path in json_files:
        try:
            strat = StrategyDefinition.model_validate_json(path.read_text())
        except Exception:
            continue
        if status and strat.status.value != status:
            continue
        color = {"active": "green", "testing": "yellow", "draft": "dim", "archived": "red"}.get(
            strat.status.value, "white"
        )
        tbl.add_row(
            strat.name, strat.version,
            f"[{color}]{strat.status.value}[/{color}]",
            ", ".join(m.value for m in strat.markets),
            ", ".join(strat.metadata.tags),
            str(path),
        )
        count += 1

    if count == 0:
        console.print("[yellow]No strategies match the filter.[/yellow]")
    else:
        console.print(tbl)

@strategies_app.command("show")
def strategies_show(path: str = typer.Argument(..., help="Path to strategy JSON")) -> None:
    """Show strategy details."""
    from rich.panel import Panel
    from rich.pretty import Pretty

    from engine.schema import StrategyDefinition

    file_path = Path(path)
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        strat = StrategyDefinition.model_validate_json(file_path.read_text())
    except Exception as exc:
        console.print(f"[red]Error: Invalid strategy JSON — {exc}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            Pretty(strat.model_dump()),
            title=f"[bold blue]{strat.name}[/bold blue] v{strat.version}  [{strat.status.value}]",
            expand=False,
        )
    )

@strategies_app.command("validate")
def strategies_validate(path: str = typer.Argument(..., help="Path to strategy JSON")) -> None:
    """Validate strategy JSON against schema."""
    from pydantic import ValidationError

    from engine.schema import StrategyDefinition

    file_path = Path(path)
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        StrategyDefinition.model_validate_json(file_path.read_text())
        console.print(f"[green]✓ {path} is valid.[/green]")
    except ValidationError as exc:
        console.print(f"[red]Validation failed for {path}:[/red]")
        for error in exc.errors():
            loc = " -> ".join(str(l) for l in error["loc"])
            console.print(f"  [yellow]{loc}[/yellow]: {error['msg']}")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Error reading file: {exc}[/red]")
        raise typer.Exit(1)

# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------

@app.command()
def optimize(
    strategy: str = typer.Option(..., "--strategy", "-s", help="Path to strategy JSON"),
    symbol: str = typer.Option(..., "--symbol", help="Ticker symbol"),
    start: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
    param_grid: str = typer.Option(..., "--param-grid", help="JSON string of param grid"),
    capital: float = typer.Option(100_000.0, "--capital", "-c", help="Initial capital"),
) -> None:
    """Optimize strategy parameters via grid search."""
    import itertools

    from engine.backtest.runner import BacktestRunner
    from engine.schema import StrategyDefinition

    strategy_path = Path(strategy)
    if not strategy_path.exists():
        console.print(f"[red]Error: Strategy file not found: {strategy}[/red]")
        raise typer.Exit(1)

    try:
        strategy_def = StrategyDefinition.model_validate_json(strategy_path.read_text())
    except Exception as exc:
        console.print(f"[red]Error: Invalid strategy JSON — {exc}[/red]")
        raise typer.Exit(1)

    try:
        grid: dict[str, list] = json.loads(param_grid)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error: Invalid param-grid JSON — {exc}[/red]")
        raise typer.Exit(1)

    param_names = list(grid.keys())
    combinations = list(itertools.product(*grid.values()))

    console.print(
        f"Grid search: [cyan]{len(combinations)}[/cyan] combinations  "
        f"for [bold]{strategy_def.name}[/bold] on [cyan]{symbol}[/cyan]"
    )

    runner = BacktestRunner()
    results: list[dict] = []

    for combo in combinations:
        params = dict(zip(param_names, combo))
        strat_dict = strategy_def.model_dump()
        for key, val in params.items():
            if key in strat_dict.get("risk", {}):
                strat_dict["risk"][key] = val
        try:
            variant = StrategyDefinition.model_validate(strat_dict)
            result = runner.run(variant, symbol, start, end, initial_capital=capital)
            results.append(
                {
                    "params": params,
                    "total_return": result.total_return,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown": result.max_drawdown,
                    "num_trades": len(result.trades),
                }
            )
        except Exception as exc:
            console.print(f"[yellow]Warning: {params} failed — {exc}[/yellow]")

    if not results:
        console.print("[red]No successful runs.[/red]")
        raise typer.Exit(1)

    results.sort(key=lambda r: r["total_return"], reverse=True)

    tbl = Table(title="Grid Search Results (by Total Return)", header_style="bold magenta")
    for name in param_names:
        tbl.add_column(name, justify="right")
    tbl.add_column("Total Return", justify="right")
    tbl.add_column("Sharpe", justify="right")
    tbl.add_column("Max DD", justify="right")
    tbl.add_column("Trades", justify="right")

    for row in results:
        color = "green" if row["total_return"] >= 0 else "red"
        tbl.add_row(
            *[str(row["params"][n]) for n in param_names],
            f"[{color}]{row['total_return']:.2%}[/{color}]",
            f"{row['sharpe_ratio']:.3f}" if row["sharpe_ratio"] is not None else "N/A",
            f"{row['max_drawdown']:.2%}" if row["max_drawdown"] is not None else "N/A",
            str(row["num_trades"]),
        )

    console.print(tbl)

# ---------------------------------------------------------------------------
# Runtime commands
# ---------------------------------------------------------------------------

@runtime_app.command("status")
def runtime_status(
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Show trading runtime status."""
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    _print_runtime_state(runtime.control.get_state())

@runtime_app.command("mode")
def runtime_mode(
    mode: str = typer.Argument(..., help="alert_only | semi_auto | auto"),
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Change the trading mode."""
    from engine.core import TradingMode
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    state = runtime.control.set_mode(TradingMode(mode))
    _print_runtime_state(state)

@runtime_app.command("pause")
def runtime_pause(
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Pause the trading runtime."""
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    state = runtime.control.pause()
    _print_runtime_state(state)

@runtime_app.command("resume")
def runtime_resume(
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Resume the trading runtime."""
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    state = runtime.control.resume()
    _print_runtime_state(state)

@runtime_app.command("emit-sample")
def runtime_emit_sample(
    symbol: str = typer.Option("BTC/USDT", "--symbol", help="Sample signal symbol"),
    action: str = typer.Option("entry", "--action", help="entry | exit"),
    side: str = typer.Option("long", "--side", help="long | short"),
    price: float = typer.Option(100_000.0, "--price", help="Entry price"),
    quantity: float = typer.Option(1.0, "--qty", help="Order quantity"),
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Emit a sample signal through the full trading runtime."""
    from engine.core import SignalAction, TradeSide, TradingSignal
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    signal = TradingSignal(
        strategy_id="manual:test",
        symbol=symbol,
        timeframe="5m",
        action=SignalAction(action),
        side=TradeSide(side),
        entry_price=price,
        stop_loss=price * 0.98 if action == "entry" else None,
        take_profits=[price * 1.02] if action == "entry" else [],
        reason="CLI sample signal",
    )
    state = runtime.orchestrator.process_signal(signal, quantity=quantity)
    _print_runtime_state(state)

@runtime_app.command("evaluate")
def runtime_evaluate(
    strategy_path: str = typer.Argument(..., help="Path to strategy JSON"),
    symbol: str = typer.Option(..., "--symbol", help="Symbol to evaluate"),
    start: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
    timeframe: str | None = typer.Option(None, "--timeframe", help="Override timeframe"),
    quantity: float = typer.Option(1.0, "--qty", help="Order quantity"),
    execute: bool = typer.Option(True, "--execute/--no-execute", help="Forward signal into runtime"),
    state_path: str = typer.Option("state/runtime_state.json", "--state", help="Runtime state path"),
) -> None:
    """Evaluate a strategy on market data and optionally route the signal into runtime."""
    from engine.application.trading.strategy_monitor import StrategyMonitorService
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime

    runtime = build_trading_runtime(TradingRuntimeConfig(state_path=state_path))
    monitor = StrategyMonitorService(runtime.orchestrator)
    strategy = monitor.load_strategy(strategy_path)
    signal = monitor.evaluate_strategy(
        strategy,
        symbol=symbol,
        start=start,
        end=end,
        timeframe=timeframe,
        quantity=quantity,
        execute=execute,
    )
    if signal is None:
        console.print("[yellow]No signal generated.[/yellow]")
        return
    console.print(
        f"signal generated: {signal.symbol} {signal.action.value} {signal.side.value} "
        f"@ {signal.entry_price:,.4f}"
    )
    if execute:
        _print_runtime_state(runtime.control.get_state())

@runtime_app.command("run-bot")
def runtime_run_bot() -> None:
    """Run the Discord control bot in the foreground."""
    from engine.interfaces.bootstrap import TradingRuntimeConfig, build_trading_runtime
    from engine.interfaces.discord.control_bot import create_bot, _load_bot_token

    token = _load_bot_token()
    if not token:
        console.print("[red]Discord bot token not configured.[/red]")
        raise typer.Exit(1)

    bot = create_bot(build_trading_runtime(TradingRuntimeConfig()).control)
    bot.run(token)

if __name__ == "__main__":
    app()

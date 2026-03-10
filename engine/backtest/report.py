"""Backtest reporting — self-contained HTML with matplotlib equity chart."""

from __future__ import annotations

import base64
import io
import os
import tempfile
from datetime import datetime
from typing import Any

import matplotlib
import matplotlib.pyplot as plt

from engine.backtest.runner import BacktestResult

matplotlib.use("Agg")

def _equity_png_b64(result: BacktestResult) -> str:
    """Render equity curve as a base64-encoded PNG string."""
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(result.equity_curve.index, result.equity_curve.values, color="#2563eb", linewidth=1.5)
    ax.set_title(f"Equity Curve — {result.symbol}")
    ax.set_ylabel("Portfolio Value")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def generate_summary(result: BacktestResult) -> dict:
    """Return a dict of key performance metrics.

    Args:
        result: BacktestResult from BacktestRunner.run().

    Returns:
        Dict with total_return, sharpe_ratio, max_drawdown, win_rate, num_trades,
        avg_return, volatility.
    """
    returns = result.equity_curve.pct_change().dropna()

    num_trades = len(result.trades)
    win_rate = (
        sum(1 for t in result.trades if t.pnl_pct > 0) / num_trades
        if num_trades > 0
        else None
    )

    summary: dict[str, Any] = {
        "total_return": result.total_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": win_rate,
        "num_trades": num_trades,
        "avg_return": float(returns.mean()) if not returns.empty else None,
        "volatility": float(returns.std()) if not returns.empty else None,
    }

    return summary

def generate_report(result: BacktestResult, output_path: str | None = None) -> str:
    """Generate a self-contained HTML backtest report.

    Args:
        result: BacktestResult from BacktestRunner.run().
        output_path: File path for the HTML report. Defaults to a temp file.

    Returns:
        Absolute path to the written HTML file.
    """
    summary = generate_summary(result)

    def _fmt_pct(v: Any) -> str:
        return f"{float(v) * 100:.2f}%" if v is not None else "N/A"

    def _fmt_f(v: Any, d: int = 4) -> str:
        return f"{float(v):.{d}f}" if v is not None else "N/A"

    pct_keys = {"total_return", "max_drawdown", "win_rate", "avg_return", "volatility"}
    summary_rows = ""
    for k, v in summary.items():
        label = k.replace("_", " ").title()
        display = _fmt_pct(v) if k in pct_keys else (str(v) if v is not None else "N/A")
        summary_rows += f"<tr><th>{label}</th><td>{display}</td></tr>"

    chart_b64 = _equity_png_b64(result) if not result.equity_curve.empty else ""
    chart_html = (
        f'<img src="data:image/png;base64,{chart_b64}" style="width:100%;max-width:900px;">'
        if chart_b64
        else "<p>No equity data available.</p>"
    )

    trade_rows = ""
    for i, t in enumerate(result.trades, 1):
        color = "#16a34a" if t.pnl_pct >= 0 else "#dc2626"
        trade_rows += (
            f"<tr><td>{i}</td><td>{t.entry_date}</td><td>{t.exit_date}</td>"
            f"<td>{_fmt_f(t.entry_price)}</td><td>{_fmt_f(t.exit_price)}</td>"
            f"<td style='color:{color}'>{_fmt_pct(t.pnl_pct)}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Backtest Report — {result.symbol}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1e293b; background: #f8fafc; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .25rem; }}
  .sub {{ color: #64748b; font-size: .9rem; margin-bottom: 2rem; }}
  section {{ background: #fff; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  h2 {{ font-size: 1.1rem; margin: 0 0 1rem; color: #475569; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .875rem; }}
  th, td {{ padding: .5rem .75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ font-weight: 600; color: #475569; }}
</style>
</head>
<body>
<h1>Backtest Report — {result.symbol}</h1>
<p class="sub">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp;
   {result.start_date} → {result.end_date} &nbsp;|&nbsp; Timeframe: {result.timeframe}</p>
<section><h2>Performance Summary</h2>
  <table><tbody>{summary_rows}</tbody></table></section>
<section><h2>Equity Curve</h2>{chart_html}</section>
<section><h2>Trade Log ({len(result.trades)} trades)</h2>
  <table>
    <thead><tr><th>#</th><th>Entry Date</th><th>Exit Date</th>
      <th>Entry Price</th><th>Exit Price</th><th>Return</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
</section>
</body>
</html>"""

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="backtest_")
        os.close(fd)

    output_path = os.path.abspath(output_path)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output_path

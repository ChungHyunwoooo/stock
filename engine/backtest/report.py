"""Backtest reporting — self-contained HTML with matplotlib equity chart.

Provides:
- generate_summary / generate_report: original single-backtest report
- generate_quantstats_report: quantstats HTML tearsheet
- generate_validation_chart: IS/OOS Sharpe bar chart (PNG)
- generate_full_report: combined HTML with equity + metrics + validation + judgment
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from engine.backtest.runner import BacktestResult
from engine.backtest.validation_result import ValidationResult

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


# ---------------------------------------------------------------------------
# New report functions (Phase 2 Plan 06)
# ---------------------------------------------------------------------------


def generate_quantstats_report(
    equity_curve: pd.Series,
    title: str = "Strategy Tearsheet",
    output: str | None = None,
    benchmark: str | None = None,
) -> str:
    """Generate quantstats HTML tearsheet from an equity curve.

    Args:
        equity_curve: Portfolio value time series.
        title: Report title.
        output: File path for HTML output. Defaults to .cache/reports/{title}.html.
        benchmark: Optional benchmark ticker for comparison.

    Returns:
        Absolute path to the written HTML file.
    """
    output_path = output or f".cache/reports/{title.replace(' ', '_')}.html"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    output_path = os.path.abspath(output_path)

    if equity_curve.empty or len(equity_curve) < 2:
        # Edge case: write a minimal HTML indicating no data
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(
                f"<!DOCTYPE html><html><head><title>{title}</title></head>"
                "<body><p>No data available for tearsheet.</p></body></html>"
            )
        return output_path

    import quantstats as qs

    returns = equity_curve.pct_change().dropna()
    qs.reports.html(
        returns,
        benchmark=benchmark,
        title=title,
        output=output_path,
        periods_per_year=252,
    )
    return output_path


def _validation_chart_b64(validation_result: ValidationResult) -> str:
    """Render IS/OOS Sharpe bar chart as base64-encoded PNG."""
    windows = validation_result.windows
    n = len(windows)
    x = np.arange(n)
    width = 0.35

    is_sharpes = [w.is_sharpe for w in windows]
    oos_sharpes = [w.oos_sharpe for w in windows]
    passed = [w.passed for w in windows]

    fig, ax = plt.subplots(figsize=(max(8, n * 1.2), 5))
    bars_is = ax.bar(x - width / 2, is_sharpes, width, label="IS Sharpe", color="#60a5fa")
    bars_oos = ax.bar(x + width / 2, oos_sharpes, width, label="OOS Sharpe", color="#34d399")

    # Color-code OOS bars by PASS/FAIL
    for bar, ok in zip(bars_oos, passed):
        bar.set_edgecolor("#16a34a" if ok else "#dc2626")
        bar.set_linewidth(2)

    # Gap threshold line
    gap_threshold = validation_result.summary.get("gap_threshold", 0.5)
    ax.axhline(y=0, color="#94a3b8", linewidth=0.5)

    mode_label = validation_result.mode.replace("_", " ").title()
    status = "PASS" if validation_result.overall_passed else "FAIL"
    ax.set_title(f"IS/OOS Sharpe — {mode_label} [{status}]")
    ax.set_xlabel("Window")
    ax.set_ylabel("Sharpe Ratio")
    ax.set_xticks(x)
    ax.set_xticklabels([f"W{w.window_idx}" for w in windows])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def generate_validation_chart(
    validation_result: ValidationResult,
    output: str | None = None,
) -> str:
    """Generate IS/OOS Sharpe bar chart as PNG.

    Args:
        validation_result: WF or CPCV validation result.
        output: File path for PNG. Defaults to .cache/reports/validation_{mode}.png.

    Returns:
        Absolute path to the written PNG file.
    """
    mode = validation_result.mode
    output_path = output or f".cache/reports/validation_{mode}.png"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    output_path = os.path.abspath(output_path)

    windows = validation_result.windows
    n = len(windows)
    x = np.arange(n)
    width = 0.35

    is_sharpes = [w.is_sharpe for w in windows]
    oos_sharpes = [w.oos_sharpe for w in windows]
    passed = [w.passed for w in windows]

    fig, ax = plt.subplots(figsize=(max(8, n * 1.2), 5))
    ax.bar(x - width / 2, is_sharpes, width, label="IS Sharpe", color="#60a5fa")
    bars_oos = ax.bar(x + width / 2, oos_sharpes, width, label="OOS Sharpe", color="#34d399")

    for bar, ok in zip(bars_oos, passed):
        bar.set_edgecolor("#16a34a" if ok else "#dc2626")
        bar.set_linewidth(2)

    ax.axhline(y=0, color="#94a3b8", linewidth=0.5)

    mode_label = mode.replace("_", " ").title()
    status = "PASS" if validation_result.overall_passed else "FAIL"
    ax.set_title(f"IS/OOS Sharpe — {mode_label} [{status}]")
    ax.set_xlabel("Window")
    ax.set_ylabel("Sharpe Ratio")
    ax.set_xticks(x)
    ax.set_xticklabels([f"W{w.window_idx}" for w in windows])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()

    fig.savefig(output_path, format="png", dpi=96)
    plt.close(fig)
    return output_path


def _compute_quantstats_metrics(returns: pd.Series) -> dict[str, str]:
    """Compute key quantstats metrics and return as formatted dict."""
    import quantstats as qs

    metrics: dict[str, str] = {}
    try:
        metrics["Total Return"] = f"{qs.stats.comp(returns) * 100:.2f}%"
        metrics["CAGR"] = f"{qs.stats.cagr(returns) * 100:.2f}%"
        metrics["Sharpe"] = f"{qs.stats.sharpe(returns):.2f}"
        metrics["Max Drawdown"] = f"{qs.stats.max_drawdown(returns) * 100:.2f}%"
        metrics["Volatility"] = f"{qs.stats.volatility(returns) * 100:.2f}%"
        calmar = qs.stats.calmar(returns)
        metrics["Calmar"] = f"{calmar:.2f}" if calmar is not None else "N/A"
    except Exception:
        pass
    return metrics


def generate_full_report(
    backtest_result: BacktestResult,
    validation_result: ValidationResult | None = None,
    output: str | None = None,
) -> str:
    """Generate comprehensive HTML report with equity, metrics, validation, judgment.

    Extends generate_report() with:
    - quantstats statistics summary table
    - IS/OOS split visualization (if validation_result provided)
    - Overall judgment with PASS/FAIL and rationale table

    Args:
        backtest_result: BacktestResult from BacktestRunner.run().
        validation_result: Optional WF/CPCV validation result.
        output: File path for HTML. Defaults to a temp file.

    Returns:
        Absolute path to the written HTML file.
    """
    summary = generate_summary(backtest_result)

    def _fmt_pct(v: Any) -> str:
        return f"{float(v) * 100:.2f}%" if v is not None else "N/A"

    # --- Performance summary table ---
    pct_keys = {"total_return", "max_drawdown", "win_rate", "avg_return", "volatility"}
    summary_rows = ""
    for k, v in summary.items():
        label = k.replace("_", " ").title()
        display = _fmt_pct(v) if k in pct_keys else (str(v) if v is not None else "N/A")
        summary_rows += f"<tr><th>{label}</th><td>{display}</td></tr>"

    # --- Equity curve chart ---
    chart_b64 = _equity_png_b64(backtest_result) if not backtest_result.equity_curve.empty else ""
    chart_html = (
        f'<img src="data:image/png;base64,{chart_b64}" style="width:100%;max-width:900px;">'
        if chart_b64
        else "<p>No equity data available.</p>"
    )

    # --- quantstats metrics ---
    qs_section = ""
    if not backtest_result.equity_curve.empty and len(backtest_result.equity_curve) >= 2:
        returns = backtest_result.equity_curve.pct_change().dropna()
        qs_metrics = _compute_quantstats_metrics(returns)
        if qs_metrics:
            qs_rows = "".join(
                f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in qs_metrics.items()
            )
            qs_section = (
                '<section><h2>Quantstats Metrics</h2>'
                f'<table><tbody>{qs_rows}</tbody></table></section>'
            )

    # --- IS/OOS validation chart ---
    validation_section = ""
    if validation_result is not None:
        val_chart_b64 = _validation_chart_b64(validation_result)
        val_img = (
            f'<img src="data:image/png;base64,{val_chart_b64}" '
            f'style="width:100%;max-width:900px;">'
        )

        # Window detail table
        win_rows = ""
        for w in validation_result.windows:
            color = "#16a34a" if w.passed else "#dc2626"
            status = "PASS" if w.passed else "FAIL"
            win_rows += (
                f"<tr><td>W{w.window_idx}</td>"
                f"<td>{w.is_sharpe:.3f}</td>"
                f"<td>{w.oos_sharpe:.3f}</td>"
                f"<td>{w.gap_ratio:.3f}</td>"
                f"<td style='color:{color};font-weight:600'>{status}</td></tr>"
            )

        mode_label = validation_result.mode.replace("_", " ").title()
        validation_section = f"""
<section><h2>IS/OOS Validation — {mode_label}</h2>
  {val_img}
  <table style="margin-top:1rem;">
    <thead><tr><th>Window</th><th>IS Sharpe</th><th>OOS Sharpe</th>
      <th>Gap Ratio</th><th>Result</th></tr></thead>
    <tbody>{win_rows}</tbody>
  </table>
</section>"""

    # --- Overall judgment ---
    judgment_section = ""
    if validation_result is not None:
        overall_status = "PASS" if validation_result.overall_passed else "FAIL"
        overall_color = "#16a34a" if validation_result.overall_passed else "#dc2626"
        n_passed = sum(1 for w in validation_result.windows if w.passed)
        n_total = len(validation_result.windows)

        rationale_rows = ""
        for k, v in validation_result.summary.items():
            rationale_rows += f"<tr><th>{k}</th><td>{v}</td></tr>"
        rationale_rows += f"<tr><th>Windows Passed</th><td>{n_passed}/{n_total}</td></tr>"

        judgment_section = f"""
<section><h2>Overall Judgment</h2>
  <p style="font-size:1.5rem;font-weight:700;color:{overall_color};">{overall_status}</p>
  <table><tbody>{rationale_rows}</tbody></table>
</section>"""

    # --- Trade log ---
    def _fmt_f(v: Any, d: int = 4) -> str:
        return f"{float(v):.{d}f}" if v is not None else "N/A"

    trade_rows = ""
    for i, t in enumerate(backtest_result.trades, 1):
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
<title>Full Backtest Report — {backtest_result.symbol}</title>
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
<h1>Full Backtest Report — {backtest_result.symbol}</h1>
<p class="sub">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp;
   {backtest_result.start_date} &rarr; {backtest_result.end_date} &nbsp;|&nbsp;
   Timeframe: {backtest_result.timeframe}</p>
<section><h2>Performance Summary</h2>
  <table><tbody>{summary_rows}</tbody></table></section>
<section><h2>Equity Curve</h2>{chart_html}</section>
{qs_section}
{validation_section}
{judgment_section}
<section><h2>Trade Log ({len(backtest_result.trades)} trades)</h2>
  <table>
    <thead><tr><th>#</th><th>Entry Date</th><th>Exit Date</th>
      <th>Entry Price</th><th>Exit Price</th><th>Return</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
</section>
</body>
</html>"""

    if output is None:
        fd, output = tempfile.mkstemp(suffix=".html", prefix="full_report_")
        os.close(fd)

    output = os.path.abspath(output)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output

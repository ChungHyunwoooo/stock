"""Top-level metrics bar component."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]


def render_metrics_bar(data: dict) -> None:
    """Render 4-column metrics bar: total PnL, win rate, avg return, total trades."""
    if st is None:
        return

    col1, col2, col3, col4 = st.columns(4)

    if data.get("total", 0) > 0:
        col1.metric("Total PnL", f"${data.get('total_profit', 0):,.2f}")
        col2.metric("Win Rate", f"{data.get('win_rate', 0):.1f}%")
        col3.metric("Avg Return", f"{data.get('avg_profit_pct', 0):.2f}%")
        col4.metric("Total Trades", f"{data.get('total', 0)}")
    else:
        col1.metric("Total PnL", "---")
        col2.metric("Win Rate", "---")
        col3.metric("Avg Return", "---")
        col4.metric("Total Trades", "---")

"""Cumulative PnL chart component."""

from __future__ import annotations

try:
    import streamlit as st
    import plotly.graph_objects as go
except ImportError:
    st = None  # type: ignore[assignment]
    go = None  # type: ignore[assignment]


def render_pnl_chart(trades: list[dict]) -> None:
    """Render cumulative PnL curve using Plotly."""
    if st is None:
        return

    if not trades:
        st.info("No closed trades to display.")
        return

    # Sort by exit_at
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_at", ""))
    cumulative = 0.0
    x_vals = []
    y_vals = []
    for t in sorted_trades:
        cumulative += t.get("pnl", 0)
        x_vals.append(t.get("exit_at", ""))
        y_vals.append(cumulative)

    if go is not None:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines",
            fill="tozeroy",
            name="Cumulative PnL",
        ))
        fig.update_layout(
            title="Cumulative PnL",
            xaxis_title="Time",
            yaxis_title="PnL ($)",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart({"Cumulative PnL": y_vals})

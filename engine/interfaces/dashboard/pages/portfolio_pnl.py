"""Portfolio PnL + strategy performance charts page."""

from __future__ import annotations

try:
    import streamlit as st
    import pandas as pd
except ImportError:
    st = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]

from engine.core.database import get_session
from engine.interfaces.dashboard.components.metrics_bar import render_metrics_bar
from engine.interfaces.dashboard.components.pnl_chart import render_pnl_chart
from engine.interfaces.dashboard.data_service import DashboardDataService


def render(service: DashboardDataService | None = None) -> None:
    """Render portfolio PnL page."""
    if st is None:
        return

    st.header("Portfolio PnL")

    svc = service or DashboardDataService()

    @st.fragment(run_every=30)
    def _portfolio_panel() -> None:
        with get_session() as session:
            # Summary metrics
            summary = svc.get_portfolio_summary(session)
            render_metrics_bar(summary)

            # PnL curve
            st.subheader("Cumulative PnL")
            closed = svc.get_closed_trades(session, limit=10000)
            render_pnl_chart(closed)

            # Open positions
            st.subheader("Open Positions")
            positions = svc.get_open_positions(session)
            if positions and pd is not None:
                st.dataframe(pd.DataFrame(positions), use_container_width=True)
            else:
                st.info("No open positions.")

            # Recent trades
            st.subheader("Recent Trades")
            recent = svc.get_closed_trades(session, limit=50)
            if recent and pd is not None:
                st.dataframe(pd.DataFrame(recent), use_container_width=True)
            else:
                st.info("No closed trades.")

    _portfolio_panel()

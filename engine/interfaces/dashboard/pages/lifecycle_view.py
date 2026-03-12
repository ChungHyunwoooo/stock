"""Strategy lifecycle status grid page."""

from __future__ import annotations

try:
    import streamlit as st
    import pandas as pd
except ImportError:
    st = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]

from engine.interfaces.dashboard.data_service import DashboardDataService

STATUSES = ["draft", "testing", "paper", "active", "archived"]


def render(service: DashboardDataService | None = None) -> None:
    """Render lifecycle overview page."""
    if st is None:
        return

    st.header("Strategy Lifecycle")

    svc = service or DashboardDataService()

    @st.fragment(run_every=30)
    def _lifecycle_panel() -> None:
        counts = svc.get_lifecycle_counts()

        # Status counts as metrics row
        cols = st.columns(len(STATUSES))
        for col, status in zip(cols, STATUSES):
            col.metric(status.capitalize(), counts.get(status, 0))

        # Strategy table
        strategies = svc.get_lifecycle_summary()
        if strategies and pd is not None:
            df = pd.DataFrame(strategies)
            display_cols = [c for c in ["id", "name", "status"] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True)
        else:
            st.info("No strategies registered.")

    _lifecycle_panel()

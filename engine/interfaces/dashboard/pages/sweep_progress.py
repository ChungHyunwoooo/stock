"""Sweep Queue Progress page -- real-time sweep monitoring.

Displays IndicatorSweeper progress from state/sweep_status.json.
Auto-refreshes every 10 seconds via @st.fragment.
"""

from __future__ import annotations

try:
    import streamlit as st
except ImportError:  # importable without streamlit for testing
    st = None  # type: ignore[assignment]

from engine.interfaces.dashboard.data_service import DashboardDataService


def render() -> None:
    """Render sweep queue progress page."""
    if st is None:
        return

    st.header("Sweep Queue")

    svc = DashboardDataService()

    @st.fragment(run_every=10)
    def _sweep_panel() -> None:
        status = svc.get_sweep_status()

        if status is None:
            st.info("No active sweep")
            return

        completed = status.get("completed", 0)
        total = status.get("total", 1)
        best_sharpe = status.get("best_sharpe", 0.0)
        candidates_found = status.get("candidates_found", 0)
        updated_at = status.get("updated_at", "")

        col1, col2, col3 = st.columns(3)
        col1.metric("Progress", f"{completed}/{total}")
        col2.metric("Best Sharpe", f"{best_sharpe:.4f}")
        col3.metric("Candidates Found", candidates_found)

        st.progress(completed / max(total, 1))

        if updated_at:
            st.caption(f"Updated: {updated_at}")

    _sweep_panel()

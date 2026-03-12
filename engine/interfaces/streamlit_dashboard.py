"""Multi-page Streamlit Trading Dashboard.

Usage: streamlit run engine/interfaces/streamlit_dashboard.py

Pages:
  - Lifecycle: strategy status grid
  - Portfolio PnL: cumulative PnL, positions, trades
  - System Health: runtime state with 30s auto-refresh
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root on PYTHONPATH
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    import streamlit as st
except ImportError:
    print("streamlit not installed. Run: pip install streamlit")
    sys.exit(1)

from engine.core.database import init_db
from engine.interfaces.dashboard.components.health_indicator import render_health
from engine.interfaces.dashboard.data_service import DashboardDataService
from engine.interfaces.dashboard.pages import (
    lifecycle_view,
    portfolio_pnl,
    settings_editor,
    sweep_progress,
)


def _health_page() -> None:
    """System Health page wrapping the health_indicator component."""
    st.header("System Health")

    svc = DashboardDataService()

    @st.fragment(run_every=30)
    def _health_panel() -> None:
        health = svc.get_system_health()
        render_health(health)

    _health_panel()


def main() -> None:
    st.set_page_config(page_title="Trading Dashboard", layout="wide")

    init_db()

    pages = st.navigation([
        st.Page(lifecycle_view.render, title="Lifecycle", icon=":material/view_list:"),
        st.Page(portfolio_pnl.render, title="Portfolio PnL", icon=":material/show_chart:"),
        st.Page(_health_page, title="System Health", icon=":material/monitor_heart:"),
        st.Page(sweep_progress.render, title="Sweep Queue", icon=":material/search:"),
        st.Page(settings_editor.render, title="Settings", icon=":material/settings:"),
    ])
    pages.run()


if __name__ == "__main__":
    main()

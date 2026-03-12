"""System health indicator component."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]


def render_health(health: dict) -> None:
    """Render system health: Mode, Paused status, paused strategy count.

    Designed to be called inside a @st.fragment(run_every=30) block.
    """
    if st is None:
        return

    col1, col2, col3 = st.columns(3)

    mode = health.get("mode", "unknown")
    paused = health.get("paused", False)
    paused_strategies = health.get("paused_strategies", set())

    col1.metric("Mode", mode)
    col2.metric("Paused", "Yes" if paused else "No")
    col3.metric("Paused Strategies", len(paused_strategies))

    updated_at = health.get("updated_at", "")
    if updated_at:
        st.caption(f"Last updated: {updated_at}")

"""Strategy Settings Editor page -- edit risk parameters via web UI.

Loads strategy definition.json, presents editable risk fields,
performs atomic write (tempfile + rename) on save.
No @st.fragment(run_every) -- interactive widgets (pitfall 3 compliance).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # importable without streamlit for testing
    st = None  # type: ignore[assignment]

from engine.interfaces.dashboard.data_service import DashboardDataService


def render() -> None:
    """Render strategy settings editor page."""
    if st is None:
        return

    st.header("Strategy Settings")

    svc = DashboardDataService()
    strategies = svc.get_lifecycle_summary()

    if not strategies:
        st.info("No strategies registered")
        return

    strategy_ids = [s.get("id", s.get("name", "unknown")) for s in strategies]
    selected_id = st.selectbox("Strategy", strategy_ids)

    if not selected_id:
        return

    def_path = Path("strategies") / selected_id / "definition.json"
    if not def_path.exists():
        st.warning(f"definition.json not found for {selected_id}")
        return

    try:
        definition = json.loads(def_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        st.error(f"Failed to read definition.json: {e}")
        return

    risk = definition.get("risk", {})

    with st.form("settings_form"):
        st.subheader("Risk Parameters")

        updated_risk = {}
        if "stop_loss_pct" in risk:
            updated_risk["stop_loss_pct"] = st.number_input(
                "Stop Loss %",
                value=float(risk["stop_loss_pct"]),
                min_value=0.0,
                step=0.1,
                format="%.2f",
            )
        if "take_profit_pct" in risk:
            updated_risk["take_profit_pct"] = st.number_input(
                "Take Profit %",
                value=float(risk["take_profit_pct"]),
                min_value=0.0,
                step=0.1,
                format="%.2f",
            )

        submitted = st.form_submit_button("Save")

        if submitted:
            # Merge updated risk fields into definition
            for key, value in updated_risk.items():
                definition["risk"][key] = value

            # Atomic write: tempfile + rename
            tmp_path = def_path.with_suffix(".tmp")
            try:
                tmp_path.write_text(
                    json.dumps(definition, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(str(tmp_path), str(def_path))
                st.success("Saved -- applied from next scan cycle")
            except OSError as e:
                st.error(f"Save failed: {e}")

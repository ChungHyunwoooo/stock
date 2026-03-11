# Phase 8: Monitoring Dashboard - Research

**Researched:** 2026-03-12
**Domain:** Streamlit web dashboard (real-time monitoring + strategy config UI)
**Confidence:** HIGH

## Summary

Phase 8 extends the existing `engine/interfaces/streamlit_dashboard.py` into a full monitoring dashboard covering the entire strategy pipeline (draft/testing/paper/active/archived), real-time positions, PnL charts, system health, sweep queue progress, and strategy config editing. The existing dashboard is a ~150-line single-page Streamlit app that reads trades from SQLite via `TradeRepository` and shows cumulative PnL + open positions. It needs significant expansion but the data layer is already solid.

Streamlit is **not currently installed** in the project venv but is available at version 1.55.0 (released 2026-03-03). Plotly 6.6.0 is already installed. The project has a mature FastAPI REST API (`api/`) with endpoints for strategies, backtests, paper trading, and health checks. The dashboard should read data directly from the domain layer (repositories, LifecycleManager, JsonRuntimeStore) rather than going through the API, following the existing pattern in `streamlit_dashboard.py`.

**Primary recommendation:** Use Streamlit 1.55.0 with `@st.fragment(run_every=30)` for 30-second auto-refresh of real-time panels. Use Plotly for interactive PnL charts. Structure as multi-page Streamlit app with `st.navigation`/`st.Page`. Read strategy configs from `strategies/registry.json` via `LifecycleManager` and write config changes back through the same manager.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MON-03 | Web dashboard: real-time positions, strategy performance, system status, sweep progress, config edit | Streamlit 1.55.0 + Plotly 6.6.0 + existing repositories + LifecycleManager + IndicatorSweeper state |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.55.0 | Web dashboard framework | Already used in project (streamlit_dashboard.py), Python-native, zero JS needed |
| plotly | 6.6.0 | Interactive charts (PnL curves, equity) | Already installed, `st.plotly_chart` native integration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas | >=2.2.0 | Data manipulation for chart data | Already installed, used in existing dashboard |
| sqlalchemy | >=2.0.25 | DB access via existing repositories | Already installed, used everywhere |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Streamlit | Dash/Plotly Dash | More flexible but requires JS knowledge, breaks existing pattern |
| Streamlit | Grafana + API | Heavyweight, separate service, overkill for this use case |
| Plotly | Altair/Vega-Lite | Altair is simpler but less interactive for financial charts |

**Installation:**
```bash
pip install streamlit>=1.55.0
```
Plotly is already installed. No other new dependencies needed.

## Architecture Patterns

### Recommended Project Structure
```
engine/interfaces/
  streamlit_dashboard.py      # EXTEND (not replace) -- entry point + navigation
  dashboard/
    __init__.py
    pages/
      __init__.py
      lifecycle_view.py        # Strategy lifecycle status grid
      portfolio_pnl.py         # Portfolio PnL + strategy performance charts
      sweep_progress.py        # Sweep queue progress panel
      settings_editor.py       # Strategy config edit UI
    components/
      __init__.py
      metrics_bar.py           # Reusable top-level metrics row
      pnl_chart.py             # Plotly PnL chart builder
      health_indicator.py      # System health status component
    data_service.py            # Dashboard data access layer (thin wrapper around repos)
```

### Pattern 1: Multi-Page Navigation with st.navigation
**What:** Streamlit 1.55.0 supports `st.navigation` + `st.Page` for multi-page apps.
**When to use:** Dashboard with 3+ distinct views.
**Example:**
```python
# streamlit_dashboard.py (entry point)
import streamlit as st

pg = st.navigation([
    st.Page("engine/interfaces/dashboard/pages/lifecycle_view.py", title="Lifecycle"),
    st.Page("engine/interfaces/dashboard/pages/portfolio_pnl.py", title="Portfolio PnL"),
    st.Page("engine/interfaces/dashboard/pages/sweep_progress.py", title="Sweep Queue"),
    st.Page("engine/interfaces/dashboard/pages/settings_editor.py", title="Settings"),
])
pg.run()
```

### Pattern 2: Fragment-Based Auto-Refresh (30s)
**What:** `@st.fragment(run_every=30)` reruns only the decorated function every 30 seconds without full page reload.
**When to use:** Real-time panels (positions, PnL, system health).
**Example:**
```python
@st.fragment(run_every=30)
def realtime_positions():
    """Auto-refreshes every 30 seconds."""
    init_db()
    with get_session() as session:
        trades = TradeRepository().list_open(session)
        df = pd.DataFrame([...])
    st.dataframe(df, use_container_width=True)
```

### Pattern 3: Data Service Layer (Thin Wrapper)
**What:** A `DashboardDataService` class that wraps existing repositories for dashboard-specific queries.
**When to use:** Avoid duplicating query logic across pages.
**Example:**
```python
class DashboardDataService:
    """Dashboard data access -- wraps existing repos, no new DB tables."""

    def __init__(self):
        self._trade_repo = TradeRepository()
        self._lifecycle = LifecycleManager()
        self._runtime_store = JsonRuntimeStore()

    def get_lifecycle_summary(self) -> list[dict]:
        """All strategies grouped by status."""
        return self._lifecycle.list_by_status()

    def get_strategy_pnl(self, session, strategy_id: str) -> dict:
        return self._trade_repo.summary(session, strategy_name=strategy_id)

    def get_system_health(self) -> dict:
        state = self._runtime_store.load()
        return {
            "mode": state.mode.value,
            "paused": state.paused,
            "paused_strategies": sorted(state.paused_strategies),
            "updated_at": state.updated_at,
        }
```

### Pattern 4: Config Edit via LifecycleManager + JSON
**What:** Strategy settings are in `strategies/{id}/definition.json`. Dashboard reads/writes through existing domain services.
**When to use:** Settings editor page.
**Example:**
```python
# Read config
strategy = lifecycle.get_strategy(strategy_id)
definition_path = Path(f"strategies/{strategy_id}/definition.json")
config = json.loads(definition_path.read_text())

# Edit via Streamlit widgets
new_threshold = st.number_input("RSI Threshold", value=config["risk"]["stop_loss_pct"])

# Write back (atomic via tempfile+rename like LifecycleManager)
if st.button("Save"):
    config["risk"]["stop_loss_pct"] = new_threshold
    # atomic write
    ...
```

### Anti-Patterns to Avoid
- **Calling FastAPI from Streamlit:** Both run in the same Python process context. Use repositories directly, not HTTP calls to localhost.
- **Full-page st.rerun for auto-refresh:** Use `@st.fragment(run_every=N)` instead -- avoids re-rendering static sections.
- **Creating new DB tables for dashboard:** All data already exists in `tse.db` + `strategies/registry.json` + `state/runtime_state.json`. Dashboard is read-only (except config edits).
- **Blocking main thread with sweep status polling:** Sweep runs in a separate process. Read Optuna journal file or a status JSON for progress, do not import/call IndicatorSweeper directly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Auto-refresh | Custom JS timer / websocket | `@st.fragment(run_every=30)` | Built into Streamlit 1.55.0, handles session lifecycle |
| PnL charts | matplotlib static charts | `st.plotly_chart` + Plotly go.Scatter | Interactive zoom/pan, native Streamlit integration |
| Multi-page routing | Custom sidebar + conditionals | `st.navigation` + `st.Page` | Built-in since Streamlit 1.36+, clean URL routing |
| Strategy status grid | Raw HTML table | `st.dataframe` with column_config | Sortable, filterable, styled cells |
| Config forms | Manual HTML forms | `st.form` + `st.number_input`/`st.toggle` | Batch submit, validation, session state |

**Key insight:** Streamlit 1.55.0 has all building blocks natively. No custom components or third-party Streamlit extensions needed.

## Common Pitfalls

### Pitfall 1: SQLite Concurrent Access
**What goes wrong:** Streamlit runs each session in a separate thread. SQLite has limited write concurrency.
**Why it happens:** Dashboard reads + config writes from multiple sessions can conflict with scanner/orchestrator writes.
**How to avoid:** Dashboard should be read-heavy. For the rare config write, use atomic tempfile+rename (same pattern as LifecycleManager._save). For SQLite reads, use `expire_on_commit=False` (already set in `get_session`).
**Warning signs:** `database is locked` errors in Streamlit logs.

### Pitfall 2: Session State Leaks
**What goes wrong:** Streamlit session_state persists across reruns but not across page navigations in multi-page apps.
**Why it happens:** Each page is a separate script execution.
**How to avoid:** Use `st.session_state` for cross-page state (e.g., selected strategy). Initialize with defaults at app entry.
**Warning signs:** KeyError on session_state access, lost selections when switching pages.

### Pitfall 3: Fragment Scope Confusion
**What goes wrong:** Widgets inside `@st.fragment` can cause unexpected reruns of the fragment.
**Why it happens:** Any widget interaction triggers fragment rerun. Combined with `run_every`, this creates race conditions.
**How to avoid:** Keep auto-refresh fragments display-only (no interactive widgets). Put interactive elements (buttons, inputs) outside fragments or in separate fragments without `run_every`.
**Warning signs:** UI flickers, form inputs reset on timer.

### Pitfall 4: Sweep Progress Access
**What goes wrong:** IndicatorSweeper uses Optuna JournalFileStorage (file-based). Reading mid-sweep can fail.
**Why it happens:** Journal file is append-only but reading partial writes can cause parse errors.
**How to avoid:** Write a separate lightweight status JSON from the sweep process (n_complete/n_total/best_sharpe). Dashboard reads this file, not the Optuna journal directly.
**Warning signs:** JSONDecodeError, stale progress numbers.

### Pitfall 5: Streamlit Not in Dependencies
**What goes wrong:** `streamlit` is not in `pyproject.toml` dependencies. Deploy will fail.
**Why it happens:** It was used ad-hoc but never added to project deps.
**How to avoid:** Add `streamlit>=1.55.0` to `[project.optional-dependencies]` under a `dashboard` extra.
**Warning signs:** ImportError on fresh deploy.

## Code Examples

### Lifecycle Status Grid with Color Coding
```python
# Source: Streamlit column_config docs
import streamlit as st
import pandas as pd

def render_lifecycle_grid(strategies: list[dict]) -> None:
    df = pd.DataFrame(strategies)

    # Status color mapping
    status_colors = {
        "draft": "gray", "testing": "blue", "paper": "orange",
        "active": "green", "archived": "red",
    }

    st.dataframe(
        df[["id", "name", "status", "sharpe"]],
        column_config={
            "status": st.column_config.TextColumn("Status", width="small"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
        },
        use_container_width=True,
    )
```

### PnL Equity Curve with Plotly
```python
import plotly.graph_objects as go
import streamlit as st

def render_pnl_chart(df: pd.DataFrame) -> None:
    """df must have 'exit_at' and 'pnl' columns."""
    df_sorted = df.sort_values("exit_at")
    df_sorted["cumulative_pnl"] = df_sorted["pnl"].cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sorted["exit_at"],
        y=df_sorted["cumulative_pnl"],
        mode="lines",
        name="Cumulative PnL",
        fill="tozeroy",
    ))
    fig.update_layout(
        title="Portfolio Equity Curve",
        xaxis_title="Date",
        yaxis_title="PnL ($)",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)
```

### Auto-Refreshing System Health Panel
```python
@st.fragment(run_every=30)
def system_health_panel():
    from engine.core.json_store import JsonRuntimeStore
    state = JsonRuntimeStore().load()

    col1, col2, col3 = st.columns(3)
    col1.metric("Mode", state.mode.value)
    col2.metric("Paused", "Yes" if state.paused else "No")
    col3.metric("Paused Strategies", len(state.paused_strategies))
    st.caption(f"Last updated: {state.updated_at}")
```

### Sweep Progress Panel
```python
import json
from pathlib import Path

@st.fragment(run_every=10)
def sweep_progress_panel():
    status_path = Path("state/sweep_status.json")
    if not status_path.exists():
        st.info("No active sweep")
        return

    status = json.loads(status_path.read_text())
    col1, col2, col3 = st.columns(3)
    col1.metric("Progress", f"{status['completed']}/{status['total']}")
    col2.metric("Best Sharpe", f"{status.get('best_sharpe', 0):.4f}")
    col3.metric("Candidates", status.get("candidates_found", 0))
    st.progress(status["completed"] / max(status["total"], 1))
```

### Settings Editor with st.form
```python
def settings_editor(strategy_id: str):
    definition_path = Path(f"strategies/{strategy_id}/definition.json")
    if not definition_path.exists():
        st.error(f"Strategy not found: {strategy_id}")
        return

    config = json.loads(definition_path.read_text())
    risk = config.get("risk", {})

    with st.form("settings_form"):
        st.subheader(f"Settings: {strategy_id}")
        stop_loss = st.number_input("Stop Loss %", value=risk.get("stop_loss_pct", 0.03), step=0.01)
        take_profit = st.number_input("Take Profit %", value=risk.get("take_profit_pct", 0.09), step=0.01)

        submitted = st.form_submit_button("Save")
        if submitted:
            config["risk"]["stop_loss_pct"] = stop_loss
            config["risk"]["take_profit_pct"] = take_profit
            # Atomic write
            import tempfile
            content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
            fd, tmp = tempfile.mkstemp(dir=definition_path.parent, suffix=".tmp")
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp).replace(definition_path)
            st.success("Saved -- applied from next scan cycle")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.experimental_fragment` | `@st.fragment` | 2025-01 (removed in Streamlit 1.41+) | Must use non-experimental API |
| `st.experimental_rerun` | `st.rerun` | 2025-01 | Scoped rerun with `scope="fragment"` |
| `pages/` directory convention | `st.navigation` + `st.Page` | Streamlit 1.36 (2024-07) | Explicit routing, no magic directory |
| `st.cache` | `st.cache_data` / `st.cache_resource` | Streamlit 1.18+ | Separate data vs resource caching |
| Manual auto-refresh (JS inject) | `@st.fragment(run_every=N)` | Streamlit 1.33+ | Native auto-refresh, no hacks |

**Deprecated/outdated:**
- `st.experimental_fragment`: Removed 2025-01. Use `@st.fragment`.
- `st.experimental_rerun`: Removed 2025-01. Use `st.rerun`.
- `pages/` directory auto-discovery: Still works but `st.navigation` is preferred for control.
- `streamlit-autorefresh` component: Unnecessary since `@st.fragment(run_every=N)` is built-in.

## Open Questions

1. **Sweep Status File Format**
   - What we know: IndicatorSweeper uses Optuna JournalFileStorage. No status JSON exists yet.
   - What's unclear: Exact fields to expose (n_complete, n_total, best_sharpe, ETA?).
   - Recommendation: Plan 08-02 should add a `state/sweep_status.json` writer to IndicatorSweeper.run() that updates after each trial.

2. **Scanner Health Detection**
   - What we know: `run_alert_scanner_background()` starts scanner in background thread. No health file.
   - What's unclear: How to detect if scanner thread is alive from Streamlit process.
   - Recommendation: Write scanner heartbeat to `state/scanner_health.json` with last_run timestamp. Dashboard checks staleness.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml (ruff only) -- pytest uses defaults |
| Quick run command | `.venv/bin/python -m pytest tests/test_dashboard.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MON-03a | Lifecycle view shows all strategy statuses | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_lifecycle_data -x` | Wave 0 |
| MON-03b | Real-time positions + PnL chart data | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_portfolio_data -x` | Wave 0 |
| MON-03c | System health (scanner/scheduler) status | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_system_health -x` | Wave 0 |
| MON-03d | Config edit writes definition.json atomically | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_config_edit -x` | Wave 0 |
| MON-03e | Sweep progress reads status JSON | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_sweep_progress -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_dashboard.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_dashboard.py` -- covers MON-03 (data service layer tests, NOT Streamlit UI tests)
- [ ] `state/sweep_status.json` writer in IndicatorSweeper -- needed for sweep progress panel

**Note:** Streamlit UI rendering cannot be unit-tested with pytest. Tests verify the data service layer (`DashboardDataService`) that feeds the UI. Visual verification is manual.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `engine/interfaces/streamlit_dashboard.py`, `engine/strategy/lifecycle_manager.py`, `engine/strategy/indicator_sweeper.py`, `engine/strategy/performance_monitor.py`, `engine/core/repository.py`, `engine/core/json_store.py`, `api/main.py`, `api/routers/strategies.py`, `api/routers/paper.py`
- [Streamlit st.fragment docs](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)
- [Streamlit 2025 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2025)
- [Streamlit st.plotly_chart docs](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart)
- [Streamlit fragments architecture](https://docs.streamlit.io/develop/concepts/architecture/fragments)
- [Streamlit PyPI](https://pypi.org/project/streamlit/) -- version 1.55.0 confirmed

### Secondary (MEDIUM confidence)
- [Algo Trading Dashboard with Streamlit](https://jaydeep4mgcet.medium.com/algo-trading-dashboard-using-python-and-streamlit-live-index-prices-current-positions-and-payoff-f44173a5b6d7) -- pattern reference
- [Streamlit + Plotly interactive dashboards](https://tildalice.io/interactive-dashboards-plotly-streamlit/)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Streamlit already in project, Plotly installed, version verified via pip
- Architecture: HIGH - All data access patterns verified from codebase (repositories, LifecycleManager, JsonRuntimeStore)
- Pitfalls: HIGH - SQLite concurrency, fragment scoping verified from docs and codebase patterns

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (Streamlit stable release cycle ~monthly)

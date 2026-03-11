---
phase: 8
slug: monitoring-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (ruff only) -- pytest uses defaults |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_dashboard.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_dashboard.py -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | MON-03a | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_lifecycle_data -x` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | MON-03b | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_portfolio_data -x` | ❌ W0 | ⬜ pending |
| 08-01-03 | 01 | 1 | MON-03c | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_system_health -x` | ❌ W0 | ⬜ pending |
| 08-02-01 | 02 | 1 | MON-03d | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_config_edit -x` | ❌ W0 | ⬜ pending |
| 08-02-02 | 02 | 1 | MON-03e | unit | `.venv/bin/python -m pytest tests/test_dashboard.py::test_sweep_progress -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dashboard.py` — stubs for MON-03 (data service layer tests, NOT Streamlit UI tests)
- [ ] `state/sweep_status.json` writer in IndicatorSweeper — needed for sweep progress panel

*Streamlit UI rendering cannot be unit-tested with pytest. Tests verify the data service layer (DashboardDataService) that feeds the UI. Visual verification is manual.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Streamlit pages render correctly | MON-03 | Streamlit UI rendering requires browser | Run `streamlit run engine/interfaces/streamlit_dashboard.py` and verify all pages load |
| 30-second auto-refresh works | MON-03b | Fragment timer requires live session | Open dashboard, observe metric updates every 30s |
| Config edit reflects on next scan | MON-03d | End-to-end requires running scanner | Edit config in dashboard, trigger scan, verify new values used |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

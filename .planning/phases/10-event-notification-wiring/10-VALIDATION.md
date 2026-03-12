---
phase: 10
slug: event-notification-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `.venv/bin/python -m pytest tests/trading/ -x -q` |
| **Full suite command** | `.venv/bin/python -m pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/trading/ -x -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | MON-01 | unit | `.venv/bin/python -m pytest tests/trading/test_event_wiring.py -x` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | MON-01 | unit | `.venv/bin/python -m pytest tests/trading/test_event_wiring.py -x` | ❌ W0 | ⬜ pending |
| 10-02-01 | 02 | 1 | DISC-01 | unit | `.venv/bin/python -m pytest tests/trading/test_backtest_events.py -x` | ❌ W0 | ⬜ pending |
| 10-02-02 | 02 | 1 | DISC-01 | unit | `.venv/bin/python -m pytest tests/trading/test_backtest_events.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/trading/test_event_wiring.py` — stubs for MON-01 (lifecycle + system error notifications)
- [ ] `tests/trading/test_backtest_events.py` — stubs for DISC-01 (backtest completion notifications)

*Existing MemoryNotifier fixture covers notification capture needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Discord message format | MON-01 | Requires live Discord webhook | Send test notification, verify embed format in channel |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

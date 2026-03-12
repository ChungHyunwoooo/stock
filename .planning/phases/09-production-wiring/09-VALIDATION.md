---
phase: 9
slug: production-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | none — default pytest discovery |
| **Quick run command** | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/trading/ -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | RISK-02 | unit | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k sizer` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | RISK-02 | unit | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k allocation` | ❌ W0 | ⬜ pending |
| 09-01-03 | 01 | 1 | RISK-02 | unit | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k blocking` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | RISK-01 | integration | `.venv/bin/python -m pytest tests/trading/test_bootstrap.py -x -k monitor` | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 1 | RISK-01+02 | integration | `.venv/bin/python -m pytest tests/trading/test_bootstrap.py -x -k assembly` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/trading/test_orchestrator.py` — update existing 4 tests for mandatory PositionSizer/PortfolioRiskManager injection
- [ ] `tests/trading/test_orchestrator.py` — add tests for sizer wiring, allocation weight, strategy blocking
- [ ] `tests/trading/test_bootstrap.py` — new file for bootstrap assembly + monitor daemon start

*Existing infrastructure covers framework needs — only test stubs required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Monitor daemon thread runs continuously | RISK-01 | Daemon lifecycle hard to test in unit tests | Start app, verify thread alive after 10s via log output |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

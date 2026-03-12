---
phase: 11
slug: cross-phase-data-contracts
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 11 — Validation Strategy

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
| 11-01-01 | 01 | 1 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/trading/test_promotion_gate.py -x` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/trading/test_promotion_gate.py -x` | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 1 | BT-05 | unit | `.venv/bin/python -m pytest tests/trading/test_cpcv_sweep.py -x` | ❌ W0 | ⬜ pending |
| 11-02-02 | 02 | 1 | BT-05 | unit | `.venv/bin/python -m pytest tests/trading/test_cpcv_sweep.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/trading/test_promotion_gate.py` — stubs for LIFE-03 (backtest baseline comparison)
- [ ] `tests/trading/test_cpcv_sweep.py` — stubs for BT-05 (CPCV mode in sweep)

*Existing test infrastructure and fixtures cover all needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

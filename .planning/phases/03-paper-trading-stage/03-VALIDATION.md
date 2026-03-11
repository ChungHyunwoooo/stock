---
phase: 3
slug: paper-trading-stage
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (기존 사용중) |
| **Config file** | tests/conftest.py |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py tests/test_promotion_gate.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py tests/test_promotion_gate.py -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | LIFE-02 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | LIFE-02 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py::test_pnl_dual_record -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | LIFE-02 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py::test_restart_restore -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_all_criteria_pass -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_criteria_fail_blocks -x` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_lifecycle_gate_integration -x` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 2 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_config_override -x` | ❌ W0 | ⬜ pending |
| 03-02-05 | 02 | 2 | LIFE-03 | unit | `.venv/bin/python -m pytest tests/test_paper_discord.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_paper_broker_persistence.py` — stubs for LIFE-02 (PaperBroker DB 영속화, PnL 이중 기록, 재시작 복원)
- [ ] `tests/test_promotion_gate.py` — stubs for LIFE-03 (승격 기준 검증, gate 통합, config 오버라이드)
- [ ] `tests/test_paper_discord.py` — stubs for LIFE-03 (Discord /전략승격 확인 버튼)

*Existing infrastructure covers framework and fixtures.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Discord 승격 알림 1회 발송 | LIFE-03 | 실제 Discord webhook 필요 | 1. paper 전략 기준 충족 시뮬레이션 2. Discord 채널에서 알림 확인 3. 중복 알림 미발송 확인 |
| Discord /전략승격 확인/취소 버튼 UX | LIFE-03 | Discord interaction 필요 | 1. `/전략승격 test_strategy` 실행 2. Embed + 버튼 표시 확인 3. 확인 클릭 → 상태 전이 확인 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

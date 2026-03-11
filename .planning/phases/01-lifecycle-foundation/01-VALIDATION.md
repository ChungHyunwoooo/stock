---
phase: 1
slug: lifecycle-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.23+ |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_lifecycle.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_lifecycle.py -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_forward_transitions -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_allowed_reverse_transitions -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_invalid_transitions -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_transition_history -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_atomic_write -x` | ❌ W0 | ⬜ pending |
| 1-01-06 | 01 | 1 | LIFE-01 | unit | `.venv/bin/python -m pytest tests/test_schema.py::test_strategy_status_enum -x` | ✅ (수정 필요) | ⬜ pending |
| 1-02-01 | 02 | 2 | LIFE-01 | integration | `.venv/bin/python -m pytest tests/test_lifecycle_discord.py -x` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 2 | LIFE-04 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_reference_strategy_valid -x` | ❌ W0 | ⬜ pending |
| 1-03-02 | 03 | 2 | LIFE-04 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_register_strategy -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_lifecycle.py` — LifecycleManager 전이 규칙 + registry.json 조작 테스트 stubs
- [ ] `tests/test_lifecycle_discord.py` — Discord 커맨드 플러그인 테스트 (mock interaction) stubs
- [ ] `tests/test_schema.py::test_strategy_status_enum` — paper 추가 반영 (기존 파일 수정)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Discord 한글 커맨드 `/전략전이` guild sync | LIFE-01 | Discord API 한글 커맨드 네이밍 실환경 테스트 필요 | 봇 배포 후 guild에서 `/전략전이` 자동완성 확인 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

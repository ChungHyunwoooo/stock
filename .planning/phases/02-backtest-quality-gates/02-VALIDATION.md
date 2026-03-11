---
phase: 2
slug: backtest-quality-gates
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 2 -- Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `.venv/bin/python -m pytest tests/ -x -q` |
| **Full suite command** | `.venv/bin/python -m pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/ -x -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | BT-01 | unit | `.venv/bin/python -m pytest tests/test_slippage.py -x` | W0 | pending |
| 02-01-02 | 01 | 1 | BT-01 | unit | `.venv/bin/python -m pytest tests/test_backtest_costs.py -x` | W0 | pending |
| 02-02-01 | 02 | 1 | BT-02 | unit | `.venv/bin/python -m pytest tests/test_walk_forward.py -x` | W0 | pending |
| 02-03-01 | 03 | 2 | BT-05 | unit | `.venv/bin/python -m pytest tests/test_cpcv.py -x` | W0 | pending |
| 02-04-01 | 04 | 2 | BT-03 | unit | `.venv/bin/python -m pytest tests/test_multi_symbol.py -x` | W0 | pending |
| 02-05-01 | 05 | 3 | BT-04 | unit | `.venv/bin/python -m pytest tests/test_backtest_history.py -x` | W0 | pending |
| 02-06-01 | 06 | 3 | BT-02, BT-05 | unit | `.venv/bin/python -m pytest tests/test_backtest_report.py -x` | W0 | pending |
| 02-07-01 | 07 | 4 | BT-04 | unit | `.venv/bin/python -m pytest tests/test_backtest_interfaces.py -x` | W0 | pending |
| 02-07-02 | 07 | 4 | BT-04 | import | `.venv/bin/python -c "from engine.interfaces.discord.commands.backtest_history import BacktestHistoryPlugin"` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Plan-to-Requirement Mapping

| Plan | Requirements | Description |
|------|-------------|-------------|
| 02-01 | BT-01 | SlippageModel + DepthCache + FeeModel + BacktestRunner 통합 |
| 02-02 | BT-02 | WalkForwardValidator (IS/OOS 분할, 성과 갭 판정) |
| 02-03 | BT-05 | CPCVValidator (조합형 퍼지 교차검증) |
| 02-04 | BT-03 | MultiSymbolValidator (상관계수 심볼 선택 + 병렬 백테스트) |
| 02-05 | BT-04 | BacktestRecord 스키마 확장 + 자동 DB 저장 + 이력 조회 |
| 02-06 | BT-02, BT-05 | quantstats 리포트 + IS/OOS 시각화 + 통합 판정 |
| 02-07 | BT-04 | CLI + API + Discord 인터페이스 (이력 조회/비교/삭제) |

---

## Wave 0 Requirements

- [ ] `tests/test_slippage.py` -- stubs for BT-01 (SlippageModel protocol, DepthCache, NoSlippage, VolumeAdjustedSlippage)
- [ ] `tests/test_backtest_costs.py` -- stubs for BT-01 (BacktestRunner slippage+fee integration)
- [ ] `tests/test_walk_forward.py` -- stubs for BT-02 (WalkForward IS/OOS split, gap judgment)
- [ ] `tests/test_multi_symbol.py` -- stubs for BT-03 (correlation selection, parallel runner, median gate)
- [ ] `tests/test_backtest_history.py` -- stubs for BT-04 (schema extension, history queries, comparison)
- [ ] `tests/test_cpcv.py` -- stubs for BT-05 (CPCV multi-path validation)
- [ ] `tests/test_backtest_report.py` -- stubs for BT-02/BT-05 (quantstats report, validation chart)
- [ ] `tests/test_backtest_interfaces.py` -- stubs for BT-04 (API + CLI interface tests)
- [ ] Framework install: `pip install skfolio` -- new dependency for WF/CPCV

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| VolumeAdjustedSlippage lowers returns vs NoSlippage | BT-01 | Requires live order book depth data | Run backtest with both models, compare PnL |
| Discord slash commands respond correctly | BT-04 | Requires running Discord bot + guild | Deploy bot, run /backtest_history in Discord |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---
phase: 11-cross-phase-data-contracts
plan: 01
subsystem: strategy
tags: [promotion-gate, backtest, cpcv, walk-forward, optuna]

requires:
  - phase: 02-backtest-infra
    provides: BacktestRepository, CPCVValidator
  - phase: 03-paper-trading
    provides: PromotionGate, PromotionCheck
  - phase: 07-strategy-sweep
    provides: IndicatorSweeper, SweepConfig
provides:
  - PromotionGate backtest baseline Sharpe check (7th criterion)
  - SweepConfig validation_mode field for CPCV/WalkForward switching
  - IndicatorSweeper CPCV validation branch with ValueError safety
affects: [01-lifecycle-foundation, 03-paper-trading, 07-strategy-sweep]

tech-stack:
  added: []
  patterns:
    - "Lazy import for CPCV to avoid circular dependency"
    - "Optional repo injection (backtest_repo=None) for backward compatibility"

key-files:
  created: []
  modified:
    - engine/strategy/promotion_gate.py
    - engine/strategy/sweep_config.py
    - engine/strategy/indicator_sweeper.py
    - tests/test_promotion_gate.py
    - tests/test_indicator_sweeper.py

key-decisions:
  - "backtest_repo optional param (None default) -- zero impact on existing callers"
  - "Paper sqrt(365) vs backtest sqrt(252) Sharpe comparison accepted as approximate gate check"
  - "CPCV ValueError returns -inf (same as WF failure) -- short equity curves silently pruned"

patterns-established:
  - "Optional repo injection pattern: constructor param with None default, conditional check in evaluate()"
  - "Lazy import inside _objective() for validator switching without top-level dependency"

requirements-completed: [LIFE-03, BT-05]

duration: 6min
completed: 2026-03-12
---

# Phase 11 Plan 01: Cross-Phase Data Contracts Summary

**PromotionGate backtest baseline Sharpe check + IndicatorSweeper CPCV validation mode via cross-phase BacktestRepository/CPCVValidator integration**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-12T06:16:46Z
- **Completed:** 2026-03-12T06:22:48Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- PromotionGate now compares paper Sharpe against backtest baseline, blocking promotion when paper underperforms
- SweepConfig supports validation_mode field ("walk_forward" or "cpcv") with backward-compatible default
- IndicatorSweeper._objective() routes to CPCVValidator when mode is "cpcv", with ValueError safety for short equity curves
- 8 new tests (4 per task), all existing tests remain green

## Task Commits

Each task was committed atomically:

1. **Task 1: PromotionGate backtest baseline Sharpe check** - `cb24014` (feat)
2. **Task 2: CPCV validation mode in IndicatorSweeper** - `4384939` (feat)

_Note: TDD tasks -- RED/GREEN phases in each commit_

## Files Created/Modified
- `engine/strategy/promotion_gate.py` - Added backtest_repo param, _get_backtest_sharpe(), backtest_sharpe check
- `engine/strategy/sweep_config.py` - Added validation_mode field with from_dict() parsing
- `engine/strategy/indicator_sweeper.py` - Added CPCV branch in _objective() with lazy import
- `tests/test_promotion_gate.py` - 4 new tests for backtest baseline Sharpe scenarios
- `tests/test_indicator_sweeper.py` - 4 new tests for validation_mode parsing and CPCV objective

## Decisions Made
- backtest_repo optional param (None default) -- zero impact on existing callers
- Paper sqrt(365) vs backtest sqrt(252) Sharpe comparison accepted as approximate gate check
- CPCV ValueError returns -inf (same as WF failure) -- short equity curves silently pruned

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Cross-phase data contracts complete
- All 11 phases finished

---
*Phase: 11-cross-phase-data-contracts*
*Completed: 2026-03-12*

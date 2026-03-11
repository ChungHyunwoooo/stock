---
phase: 02-backtest-quality-gates
plan: 04
subsystem: backtest
tags: [multi-symbol, correlation, parallel, ProcessPoolExecutor, median-sharpe, greedy-selection]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    provides: BacktestRunner with slippage+fee, SlippageModel Protocol, BacktestResult with sharpe_ratio
provides:
  - select_uncorrelated_symbols (greedy correlation-based symbol selector)
  - MultiSymbolResult dataclass (per-symbol Sharpe + median gate)
  - MultiSymbolValidator (ProcessPoolExecutor parallel backtest + median Sharpe judgment)
  - _run_symbol_backtest (pickle-safe top-level worker)
affects: [02-05 DB persistence, future pipeline integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [ProcessPoolExecutor parallel backtest with pickle-safe worker, _validate_sequential for testable mock path]

key-files:
  created:
    - engine/backtest/multi_symbol.py
    - tests/test_multi_symbol.py
  modified: []

key-decisions:
  - "Greedy correlation selection: first symbol always included, then add if |corr| < max_corr with all selected"
  - "_validate_sequential method for mock-friendly testing without ProcessPoolExecutor pickle issues"
  - "_build_result extracts shared result logic used by both parallel and sequential paths"
  - "Failed symbol backtests skipped with warning, not fatal -- partial results accepted"

patterns-established:
  - "MultiSymbol parallel pattern: top-level worker + _validate_sequential for testing + _build_result shared logic"
  - "Correlation-based greedy selection: O(n*k) with pairwise check against selected set"

requirements-completed: [BT-03]

# Metrics
duration: 3min
completed: 2026-03-11
---

# Phase 2 Plan 04: Multi-Symbol Parallel Backtest + Correlation-Based Symbol Selection Summary

**Greedy correlation selector (|r| < 0.5) + ProcessPoolExecutor parallel backtest + median Sharpe >= 0.5 gate for strategy robustness verification**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-11T09:19:15Z
- **Completed:** 2026-03-11T09:22:21Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- select_uncorrelated_symbols with greedy pairwise |corr| < max_corr selection from returns DataFrame
- MultiSymbolResult dataclass with per-symbol Sharpe, median Sharpe, and threshold-based pass/fail
- MultiSymbolValidator with ProcessPoolExecutor parallel execution via pickle-safe _run_symbol_backtest worker
- _validate_sequential method for testable mock-friendly execution without subprocess pickle constraints
- 12 tests passing (4 selection + 3 result + 5 validator)

## Task Commits

Each task was committed atomically:

1. **Task 1: select_uncorrelated_symbols + MultiSymbolResult + tests** - `2e78824` (feat)
2. **Task 2: MultiSymbolValidator parallel backtest + median Sharpe gate** - `6f54495` (feat)

_Both tasks followed TDD: RED (failing tests) -> GREEN (implementation) -> verify_

## Files Created/Modified
- `engine/backtest/multi_symbol.py` - select_uncorrelated_symbols + MultiSymbolResult + MultiSymbolValidator + _run_symbol_backtest worker
- `tests/test_multi_symbol.py` - 12 tests covering symbol selection, result logic, and validator behavior

## Decisions Made
- Greedy selection starts with first symbol, adds candidates checking |corr| < max_corr against all already-selected symbols
- _validate_sequential provides mock-friendly test path -- avoids ProcessPoolExecutor pickle issues with unittest.mock
- _build_result shared between validate() and _validate_sequential() to avoid logic duplication
- Failed symbol backtests produce (symbol, None) and are skipped with warning -- partial results accepted for median calculation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing test failure in tests/test_broker.py::TestUpbitBroker (missing upbit_broker module) -- documented as out of scope, same as plan 02-01

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- MultiSymbolValidator ready for integration with DB persistence (plan 02-05)
- select_uncorrelated_symbols can be used standalone for symbol screening
- ProcessPoolExecutor pattern proven and testable via _validate_sequential

## Self-Check: PASSED

- engine/backtest/multi_symbol.py: FOUND
- tests/test_multi_symbol.py: FOUND
- Commit 2e78824: FOUND
- Commit 6f54495: FOUND
- 12/12 new tests passing
- 316 existing tests passing (1 pre-existing failure excluded)

---
*Phase: 02-backtest-quality-gates*
*Completed: 2026-03-11*

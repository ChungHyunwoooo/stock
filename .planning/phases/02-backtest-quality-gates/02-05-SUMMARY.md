---
phase: 02-backtest-quality-gates
plan: 05
subsystem: database
tags: [sqlalchemy, sqlite, migration, repository, backtest-history, auto-save]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    provides: SlippageModel Protocol, BacktestRunner cost injection, BacktestRecord base schema
provides:
  - BacktestRecord Phase 2 columns (slippage_model, fee_rate, wf_result, cpcv_mode, multi_symbol_result)
  - _migrate_backtests_phase2 conditional SQLite migration (idempotent)
  - BacktestRepository history/compare/delete methods
  - BacktestRunner auto DB save on run() completion
affects: [API backtest history endpoints, CLI backtest comparison, Discord backtest commands]

# Tech tracking
tech-stack:
  added: []
  patterns: [conditional SQLite migration via PRAGMA table_info, auto-save with warning-only failure]

key-files:
  created:
    - tests/test_backtest_history.py
  modified:
    - engine/core/db_models.py
    - engine/core/repository.py
    - engine/core/database.py
    - engine/backtest/runner.py

key-decisions:
  - "Auto-save uses try/except with logger.warning -- DB failure never blocks backtest result"
  - "Migration uses PRAGMA table_info + ALTER TABLE ADD COLUMN -- no Alembic dependency"
  - "slippage_model column stores class name (e.g. 'NoSlippage', 'VolumeAdjustedSlippage') via type().__name__"
  - "get_history returns DESC order (newest first), compare_strategies returns all records for given strategy_ids"

patterns-established:
  - "SQLite conditional migration: PRAGMA table_info check + ALTER TABLE ADD COLUMN (idempotent, no data loss)"
  - "Auto-save pattern: warning-only failure for non-critical persistence in hot path"

requirements-completed: [BT-04]

# Metrics
duration: 4min
completed: 2026-03-11
---

# Phase 2 Plan 05: BacktestRecord DB Persistence + History Comparison Summary

**BacktestRecord schema extended with 5 Phase 2 columns, auto-save on BacktestRunner.run() completion, idempotent SQLite migration, and repository history/compare/delete methods**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-11T09:25:01Z
- **Completed:** 2026-03-11T09:29:08Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- BacktestRecord extended with slippage_model, fee_rate, wf_result, cpcv_mode, multi_symbol_result columns
- _migrate_backtests_phase2() adds missing columns to existing SQLite DB without data loss (idempotent)
- BacktestRepository: get_history (DESC), compare_strategies (cross-strategy), delete, delete_by_strategy
- BacktestRunner.run() auto-saves to DB when auto_save=True + strategy_id set; failure is warning-only
- 17 tests covering schema extension, migration, history, compare, delete, auto-save, failure handling

## Task Commits

Each task was committed atomically:

1. **Task 1: BacktestRecord schema + migration + repository history/compare/delete** - `70278b2` (feat) [TDD]
2. **Task 2: BacktestRunner auto DB save integration** - `7964f66` (feat)

## Files Created/Modified
- `engine/core/db_models.py` - BacktestRecord Phase 2 column additions (slippage_model, fee_rate, wf_result, cpcv_mode, multi_symbol_result)
- `engine/core/database.py` - _migrate_backtests_phase2() + init_db() migration call
- `engine/core/repository.py` - BacktestRepository get_history, compare_strategies, delete, delete_by_strategy
- `engine/backtest/runner.py` - auto_save + strategy_id params, _save_to_db() with warning-only failure
- `tests/test_backtest_history.py` - 17 tests for schema, migration, repository, auto-save

## Decisions Made
- Auto-save failure is warning-only (logger.warning) -- backtest result always returned normally
- Migration uses PRAGMA table_info for column detection -- no Alembic dependency needed
- slippage_model stored as class name string (type(self._slippage_model).__name__)
- get_history returns created_at DESC with configurable limit (default 100)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing test failure in tests/test_broker.py::TestUpbitBroker (missing upbit_broker module) -- documented as out of scope, same as plan 02-01

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- BacktestRecord schema ready for WF/CPCV/multi-symbol result storage
- Auto-save infrastructure ready for all BacktestRunner consumers
- History comparison ready for CLI/API/Discord interface plans
- 346 existing tests passing (1 pre-existing failure excluded)

## Self-Check: PASSED

- All 5 files verified present
- Commit 70278b2 verified
- Commit 7964f66 verified
- 17/17 new tests passing
- 346 existing tests passing (1 pre-existing failure excluded)

---
*Phase: 02-backtest-quality-gates*
*Completed: 2026-03-11*

---
phase: 03-paper-trading-stage
plan: 01
subsystem: database
tags: [sqlalchemy, sqlite, paper-trading, persistence, repository]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    provides: DB migration pattern, Repository pattern, TradeRepository
provides:
  - PaperBalance / PaperPnlSnapshot SQLAlchemy models
  - PaperRepository CRUD (save_balance, get_latest, upsert snapshot, get_strategies)
  - _migrate_paper_phase3() idempotent migration
  - PaperBroker DB persistence (save/restore balance, daily PnL snapshot)
  - config/paper_trading.json (promotion gates defaults, timeframe min trades)
affects: [03-paper-trading-stage]

# Tech tracking
tech-stack:
  added: []
  patterns: [PaperBroker DB persistence with try/except safe writes, PnL snapshot upsert via ORM merge]

key-files:
  created:
    - config/paper_trading.json
    - tests/test_paper_broker_persistence.py
  modified:
    - engine/core/db_models.py
    - engine/core/database.py
    - engine/core/repository.py
    - engine/execution/paper_broker.py

key-decisions:
  - "strategy_id defaults to 'default' for backward compatibility with existing PaperBroker() callers"
  - "DB failure in save_balance_snapshot never blocks trade execution (try/except + logger.warning)"
  - "PaperPnlSnapshot upsert via ORM query-then-update instead of raw INSERT OR REPLACE for SQLAlchemy compatibility"
  - "TradeRepository.list_open extended with strategy_name + broker filters for PaperBroker position restore"

patterns-established:
  - "Phase 3 DB migration: _migrate_paper_phase3() with CREATE TABLE IF NOT EXISTS"
  - "PaperRepository upsert pattern: query existing by unique key, update if found, insert if not"
  - "PaperBroker DB engine singleton reset for test isolation"

requirements-completed: [LIFE-02]

# Metrics
duration: 7min
completed: 2026-03-11
---

# Phase 3 Plan 01: PaperBroker DB Persistence Summary

**PaperBroker SQLite persistence with PaperBalance/PaperPnlSnapshot models, PaperRepository CRUD, and strategy-isolated balance save/restore**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-11T14:50:14Z
- **Completed:** 2026-03-11T14:57:13Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- PaperBalance/PaperPnlSnapshot SQLAlchemy models with UNIQUE(strategy_id, date) constraint
- PaperRepository with save_balance, get_latest_balance, save_daily_snapshot (upsert), get_daily_snapshots, get_paper_strategies
- PaperBroker DB persistence: balance save/restore on init, snapshot after each trade, daily PnL aggregation
- config/paper_trading.json with promotion gate defaults and timeframe-based min_trades mapping
- 22 new tests covering models, migration, repository, and PaperBroker integration

## Task Commits

Each task was committed atomically (TDD: test -> feat):

1. **Task 1: DB Models + Migration + PaperRepository + Config**
   - `890bb1f` (test) - Failing tests for models, migration, repository, config
   - `967e722` (feat) - PaperBalance/PaperPnlSnapshot models, _migrate_paper_phase3, PaperRepository, config
2. **Task 2: PaperBroker DB Persistence**
   - `76b3bdb` (test) - Failing tests for PaperBroker persistence
   - `0d75597` (feat) - PaperBroker save/restore, TradeRepository.list_open extension

## Files Created/Modified
- `engine/core/db_models.py` - PaperBalance, PaperPnlSnapshot models
- `engine/core/database.py` - _migrate_paper_phase3() idempotent migration + init_db integration
- `engine/core/repository.py` - PaperRepository class + TradeRepository.list_open extended filters
- `engine/execution/paper_broker.py` - DB persistence: strategy_id, save/restore, daily snapshot
- `config/paper_trading.json` - Promotion gates defaults + timeframe min trades
- `tests/test_paper_broker_persistence.py` - 22 tests for all new functionality

## Decisions Made
- strategy_id defaults to "default" for backward compatibility -- existing `PaperBroker()` callers (broker_factory, plugin_runtime, test_broker) continue working without changes
- DB failure during save never blocks trade execution -- Phase 2 established pattern (try/except + logger.warning)
- PaperPnlSnapshot upsert uses ORM query-then-update rather than raw SQL INSERT OR REPLACE for SQLAlchemy session consistency
- TradeRepository.list_open extended with optional strategy_name/broker params (backward compatible)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed backward compatibility for PaperBroker signature**
- **Found during:** Task 2 (regression test)
- **Issue:** Making strategy_id required broke 15+ existing callers (test_broker, broker_factory, plugin_runtime, orchestrator tests)
- **Fix:** Changed strategy_id to default="default" instead of required
- **Files modified:** engine/execution/paper_broker.py
- **Verification:** All 403 existing tests pass
- **Committed in:** 0d75597 (Task 2 commit)

**2. [Rule 3 - Blocking] Extended TradeRepository.list_open with strategy_name/broker filters**
- **Found during:** Task 2 (PaperBroker position restore)
- **Issue:** list_open only supported symbol filter; PaperBroker needs strategy_name + broker filters for isolated position restore
- **Fix:** Added optional strategy_name and broker parameters (backward compatible)
- **Files modified:** engine/core/repository.py
- **Verification:** TestTradeRepositoryListOpenExtended passes
- **Committed in:** 0d75597 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes necessary for correctness and backward compatibility. No scope creep.

## Issues Encountered
- DB engine singleton in database.py causes test isolation issues when multiple PaperBroker instances use different db_url values -- resolved by resetting _engine in test fixture teardown

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PaperBroker persistence foundation ready for Plan 02 (promotion gate) and Plan 03 (3-channel interface)
- PaperRepository provides the data access layer for paper performance queries
- config/paper_trading.json provides promotion gate defaults for PromotionGate class

---
*Phase: 03-paper-trading-stage*
*Completed: 2026-03-11*

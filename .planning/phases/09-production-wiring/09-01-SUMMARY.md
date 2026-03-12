---
phase: 09-production-wiring
plan: 01
subsystem: execution
tags: [position-sizer, portfolio-risk, orchestrator, atr-kelly, risk-parity]

requires:
  - phase: 04-portfolio-risk
    provides: PositionSizer and PortfolioRiskManager implementations
provides:
  - PositionSizer wired into TradingOrchestrator.process_signal() for dynamic ATR/Kelly sizing
  - PortfolioRiskManager mandatory injection with allocation weight gating
  - Unregistered strategy blocking at portfolio risk level
affects: [09-production-wiring, execution]

tech-stack:
  added: []
  patterns: [transient-metadata-pattern, mandatory-dependency-injection]

key-files:
  created: []
  modified:
    - engine/application/trading/orchestrator.py
    - engine/application/trading/signal_scanner.py
    - engine/application/trading/strategy_monitor.py
    - engine/interfaces/bootstrap.py
    - engine/cli.py
    - tests/trading/test_orchestrator.py
    - tests/test_mtf_filter.py
    - tests/test_performance_monitor.py
    - tests/test_portfolio_risk.py

key-decisions:
  - "Transient metadata pattern: ohlcv_df and returns stripped from signal.metadata before state persistence, restored after processing"
  - "Mock broker in unit tests: replaced PaperBroker with MagicMock to avoid SQLite DB dependency in orchestrator tests"
  - "position_sizer and portfolio_risk are None-defaulted in constructor but ValueError raised at process_signal time for semi_auto/auto modes"

patterns-established:
  - "Transient metadata: non-serializable objects (DataFrames, Series) stripped before JSON persistence, read from transient dict during processing"
  - "Mock broker pattern: BrokerPort mock with execute_order side_effect for unit tests avoiding DB"

requirements-completed: [RISK-02]

duration: 12min
completed: 2026-03-12
---

# Phase 09 Plan 01: PositionSizer + PortfolioRiskManager Wiring Summary

**ATR/Kelly dynamic sizing wired into orchestrator with mandatory PortfolioRiskManager injection and unregistered strategy blocking**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-12T04:40:35Z
- **Completed:** 2026-03-12T04:52:55Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- process_signal() now computes quantity internally via PositionSizer.calculate() with OHLCV, capital, allocation_weight
- PortfolioRiskManager.get_allocation_weights() gates every auto/semi_auto order
- Unregistered strategies (not in allocation weights) are blocked from entry
- signal_scanner and strategy_monitor attach OHLCV DataFrame to signal metadata for downstream sizing
- All 512 tests pass (3 pre-existing failures excluded: upbit_broker, lifecycle, plugin_registry)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update tests for mandatory PositionSizer/PortfolioRiskManager injection** - `0fa7498` (test) - RED phase: 8 tests written, 6 failing
2. **Task 2: Wire PositionSizer + PortfolioRiskManager into orchestrator + update callers** - `a3e370f` (feat) - GREEN phase: all 8 tests passing + 504 other tests

## Files Created/Modified
- `engine/application/trading/orchestrator.py` - Mandatory sizer/portfolio_risk injection, sizing flow in full_auto path, transient metadata handling
- `engine/application/trading/signal_scanner.py` - Attach ohlcv_df to signals, remove quantity= from process_signal calls
- `engine/application/trading/strategy_monitor.py` - Attach ohlcv_df to signals, remove quantity= from process_signal call
- `engine/interfaces/bootstrap.py` - Inject position_sizer into orchestrator constructor
- `engine/cli.py` - Remove quantity= from CLI process_signal call
- `tests/trading/test_orchestrator.py` - 8 tests with mock broker, sizer, portfolio_risk
- `tests/test_mtf_filter.py` - Updated MTF integration tests with sizer/portfolio_risk mocks
- `tests/test_performance_monitor.py` - Updated non_paused_strategy test with sizer/portfolio_risk mocks
- `tests/test_portfolio_risk.py` - Updated orchestrator integration tests with sizer injection

## Decisions Made
- Transient metadata pattern: ohlcv_df and returns stripped from signal.metadata before state persistence to avoid JSON serialization of DataFrames, restored after processing for caller compatibility
- Mock broker in unit tests: replaced PaperBroker with MagicMock to avoid SQLite paper_balances table dependency
- position_sizer/portfolio_risk None-defaulted in constructor for backward compatibility but ValueError at runtime for semi_auto/auto modes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] JSON serialization failure from DataFrame in metadata**
- **Found during:** Task 2
- **Issue:** signal.metadata["ohlcv_df"] (DataFrame) caused JSON serialization error when runtime_store.save() called
- **Fix:** Transient metadata pattern -- strip non-serializable keys before processing, restore after
- **Files modified:** engine/application/trading/orchestrator.py
- **Committed in:** a3e370f

**2. [Rule 3 - Blocking] Updated MTF/portfolio_risk/performance_monitor tests**
- **Found during:** Task 2
- **Issue:** Existing tests created TradingOrchestrator without position_sizer, failing with ValueError on auto mode
- **Fix:** Updated all affected tests to inject mock position_sizer and portfolio_risk
- **Files modified:** tests/test_mtf_filter.py, tests/test_performance_monitor.py, tests/test_portfolio_risk.py
- **Committed in:** a3e370f

**3. [Rule 3 - Blocking] Updated additional callers of process_signal**
- **Found during:** Task 2
- **Issue:** engine/cli.py and engine/application/trading/strategy_monitor.py also called process_signal(quantity=)
- **Fix:** Removed quantity= parameter, attached ohlcv_df to signal metadata
- **Files modified:** engine/cli.py, engine/application/trading/strategy_monitor.py
- **Committed in:** a3e370f

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking)
**Impact on plan:** All auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PositionSizer fully wired into production execution path
- Ready for Phase 09 Plan 02 (bootstrap assembly) and remaining production wiring

---
*Phase: 09-production-wiring*
*Completed: 2026-03-12*

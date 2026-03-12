---
phase: 10-event-notification-wiring
plan: 01
subsystem: notifications
tags: [event-notifier, discord, lifecycle, backtest, bootstrap]

requires:
  - phase: 06-event-notifier
    provides: EventNotifier class with 4 notify methods
  - phase: 09-production-wiring
    provides: TradingOrchestrator with event_notifier param, bootstrap build_trading_runtime

provides:
  - EventNotifier wired into bootstrap (orchestrator + lifecycle + system_error)
  - BacktestRunner event_notifier injection with [BACKTEST] notification on run()
  - IndicatorSweeper per-candidate [BACKTEST] notification
  - BacktestHistoryPlugin confirmed in DEFAULT_COMMAND_PLUGINS

affects: [11-discord-ux-polish]

tech-stack:
  added: []
  patterns: [optional-injection-with-try-except-notification, lambda-callback-for-lifecycle-listener]

key-files:
  created: []
  modified:
    - engine/interfaces/bootstrap.py
    - engine/backtest/runner.py
    - engine/strategy/indicator_sweeper.py
    - tests/test_event_notifier.py

key-decisions:
  - "Bootstrap try/except wraps post-event_notifier initialization only -- event_notifier creation failure falls through to existing error handling"
  - "IndicatorSweeper _notify_results (summary) preserved alongside EventNotifier (per-candidate) -- role separation"
  - "StrategyPerformanceMonitor.run_daemon mocked in bootstrap test to avoid daemon thread in tests"

patterns-established:
  - "Optional event_notifier injection: always default=None, guard with if-not-None, wrap in try/except"

requirements-completed: [MON-01, DISC-01]

duration: 4min
completed: 2026-03-12
---

# Phase 10 Plan 01: Event Notification Wiring Summary

**EventNotifier wired into bootstrap/BacktestRunner/IndicatorSweeper with lifecycle callback, backtest completion, and system error notifications**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-12T06:02:12Z
- **Completed:** 2026-03-12T06:06:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- EventNotifier created in build_trading_runtime() and injected into orchestrator + lifecycle + TradingRuntime
- BacktestRunner.run() sends [BACKTEST] notification on completion via optional event_notifier
- IndicatorSweeper._register_candidates() sends per-candidate [BACKTEST] notification
- Bootstrap try/except calls notify_system_error on initialization failure
- All backward compatibility preserved (no-arg construction works)
- 17 tests passing (9 existing + 8 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Bootstrap EventNotifier wiring + BacktestRunner event_notifier injection** - `76184d6` (feat)
2. **Task 2: IndicatorSweeper event_notifier injection** - `0aea87f` (feat)

## Files Created/Modified
- `engine/interfaces/bootstrap.py` - EventNotifier creation, lifecycle listener, orchestrator injection, system_error try/except
- `engine/backtest/runner.py` - Optional event_notifier param, notify_backtest_complete after run()
- `engine/strategy/indicator_sweeper.py` - Optional event_notifier param, per-candidate notification in _register_candidates()
- `tests/test_event_notifier.py` - 8 new test classes: bootstrap wiring, backtest notification, backward compat, plugin registration, system error, sweeper notification/compat/no-candidate

## Decisions Made
- Bootstrap try/except wraps post-event_notifier initialization only -- event_notifier creation failure falls through to existing error handling
- IndicatorSweeper _notify_results (summary Discord) preserved alongside EventNotifier (per-candidate) -- role separation
- StrategyPerformanceMonitor.run_daemon mocked in bootstrap test to avoid daemon thread

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All EventNotifier methods now wired to production call paths
- MON-01 (real-time Discord alerts for trade/lifecycle/backtest/system) complete
- DISC-01 notification aspect complete (sweep candidates notified via EventNotifier)
- Ready for Phase 11 Discord UX polish

---
## Self-Check: PASSED

All files found. Commits 76184d6 and 0aea87f verified.

---
*Phase: 10-event-notification-wiring*
*Completed: 2026-03-12*

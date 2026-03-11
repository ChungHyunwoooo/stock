---
phase: 05-performance-monitoring
plan: "01"
subsystem: strategy
tags: [sharpe, rolling-window, performance-monitor, daemon-thread, per-strategy-pause]

requires:
  - phase: 03-paper-trading
    provides: TradeRepository.list_closed, PaperBroker trade records
  - phase: 01-lifecycle-foundation
    provides: LifecycleManager.list_by_status, StrategyStatus FSM
provides:
  - StrategyPerformanceMonitor with rolling Sharpe/win_rate evaluation
  - PerformanceConfig / PerformanceSnapshot dataclasses
  - Per-strategy pause via TradingRuntimeState.paused_strategies
  - Daemon thread for periodic performance checks
affects: [05-performance-monitoring, 06-alert-mtf]

tech-stack:
  added: []
  patterns: [rolling-window-metrics, daemon-thread-isolation, per-strategy-pause]

key-files:
  created:
    - engine/strategy/performance_monitor.py
    - tests/test_performance_monitor.py
  modified:
    - engine/core/models.py
    - engine/core/json_store.py
    - engine/application/trading/orchestrator.py

key-decisions:
  - "Pure Python Sharpe (mean/std) -- no numpy dependency for monitor"
  - "set->sorted list->set for paused_strategies JSON serialization"
  - "Daemon thread with per-strategy try/except -- one failure never blocks others"

patterns-established:
  - "Rolling window pattern: _compute_rolling_metrics(trades, window) -> (sharpe, win_rate)"
  - "Alert level escalation: none -> warning (15% degradation) -> critical (Sharpe < -0.5)"

requirements-completed: [RISK-01]

duration: 2min
completed: 2026-03-11
---

# Phase 05 Plan 01: StrategyPerformanceMonitor Summary

**Rolling window Sharpe/win_rate monitor with baseline comparison, WARNING/CRITICAL alerts, and per-strategy pause in Orchestrator**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-11T19:35:25Z
- **Completed:** 2026-03-11T19:37:51Z
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments
- StrategyPerformanceMonitor computes 20-trade rolling Sharpe/win_rate and compares against backtest baseline
- WARNING alert at 15%+ degradation, CRITICAL at extended-window Sharpe < -0.5 (auto-pauses strategy)
- paused_strategies field added to TradingRuntimeState with full JSON serialization roundtrip
- Orchestrator skips signals for paused strategies with notification
- Daemon thread runs independently -- monitor failure never affects trading

## Task Commits

Each task was committed atomically:

1. **Task 1: Per-strategy pause + StrategyPerformanceMonitor** - `db03fab` (feat)

## Files Created/Modified
- `engine/strategy/performance_monitor.py` - PerformanceConfig, PerformanceSnapshot, StrategyPerformanceMonitor
- `engine/core/models.py` - Added paused_strategies: set[str] to TradingRuntimeState
- `engine/core/json_store.py` - Serialize/deserialize paused_strategies (set<->list)
- `engine/application/trading/orchestrator.py` - Per-strategy pause check in process_signal
- `tests/test_performance_monitor.py` - 11 unit tests (metrics, alerts, serialization, orchestrator)

## Decisions Made
- Pure Python Sharpe calculation (mean/std) -- no numpy dependency needed for simple rolling metrics
- paused_strategies serialized as sorted list for deterministic JSON output
- Daemon thread isolates each strategy evaluation with try/except -- one failure never blocks others
- Zero-std case returns sharpe=0.0 (all trades identical profit)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PerformanceMonitor ready for 05-02 AlertDispatcher integration
- paused_strategies mechanism available for manual unpause commands

---
*Phase: 05-performance-monitoring*
*Completed: 2026-03-11*

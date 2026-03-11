---
phase: 05-performance-monitoring
plan: "02"
subsystem: notifications
tags: [discord, embed, performance-alert, auto-pause]

requires:
  - phase: 05-01
    provides: StrategyPerformanceMonitor with PerformanceSnapshot, check_all, rolling metrics
provides:
  - send_performance_alert Discord embed method (WARNING orange, CRITICAL red)
  - Auto-pause on CRITICAL via paused_strategies + runtime_store
  - MemoryNotifier.send_performance_alert for testing
affects: [06-alert-mtf-enrichment]

tech-stack:
  added: []
  patterns: [embed-based Discord alerts with color-coded severity]

key-files:
  created: []
  modified:
    - engine/core/ports.py
    - engine/notifications/discord_webhook.py
    - engine/strategy/performance_monitor.py
    - tests/test_performance_monitor.py

key-decisions:
  - "getattr for snapshot fields in Discord notifier -- avoids circular import of PerformanceSnapshot"
  - "send_performance_alert replaces send_text in handlers -- richer embed vs plain text"

patterns-established:
  - "Performance alert embed pattern: color-coded severity, structured fields, footer with timestamp"

requirements-completed: [RISK-01]

duration: 2min
completed: 2026-03-11
---

# Phase 5 Plan 02: Discord Performance Alert + Auto-Pause Summary

**Discord WARNING/CRITICAL embed alerts with Sharpe/win-rate metrics and automatic strategy pause on critical degradation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-11T19:39:52Z
- **Completed:** 2026-03-11T19:41:51Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments
- WARNING embed (orange 0xFFA500) with Sharpe/win-rate degradation details sent on 15%+ baseline drop
- CRITICAL embed (red 0xFF0000) with auto-pause: strategy added to paused_strategies, persisted via runtime_store
- NotificationPort protocol extended with send_performance_alert
- 7 new tests covering embed colors, field content, pause isolation, healthy no-alert

## Task Commits

Each task was committed atomically:

1. **Task 1: Discord embed alert + auto-pause (TDD)** - `cf67dc5` (feat)

## Files Created/Modified
- `engine/core/ports.py` - Added send_performance_alert to NotificationPort protocol
- `engine/notifications/discord_webhook.py` - DiscordWebhookNotifier.send_performance_alert embed implementation + MemoryNotifier.send_performance_alert
- `engine/strategy/performance_monitor.py` - _handle_critical/_handle_warning use send_performance_alert instead of send_text
- `tests/test_performance_monitor.py` - 7 new tests for alert embed + pause behavior

## Decisions Made
- Used getattr for snapshot field access in DiscordWebhookNotifier to avoid circular import of PerformanceSnapshot dataclass
- Replaced send_text calls in handlers with send_performance_alert for structured embed alerts

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing test failure in tests/trading/test_plugin_registry.py (discord command registry) -- not caused by this plan's changes, out of scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- RISK-01 chain complete: performance monitor -> alert -> auto-pause
- Ready for Phase 6 (Alert & MTF Enrichment)

---
*Phase: 05-performance-monitoring*
*Completed: 2026-03-11*

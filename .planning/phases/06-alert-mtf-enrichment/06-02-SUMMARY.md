---
phase: 6
plan: "06-02"
subsystem: discord-commands
tags: [discord, status, positions, pnl]
dependency_graph:
  requires: [TradingControlService, LifecycleManager, formatting]
  provides: [StatusCommandPlugin, format_status_embed]
  affects: [engine/interfaces/discord/commands, engine/interfaces/discord/formatting]
tech_stack:
  added: []
  patterns: [defer-followup, plugin-protocol]
key_files:
  created:
    - engine/interfaces/discord/commands/status.py
    - tests/test_status_command.py
  modified:
    - engine/interfaces/discord/commands/__init__.py
    - engine/interfaces/discord/commands/runtime.py
    - engine/interfaces/discord/formatting.py
decisions:
  - "StatusCommandPlugin replaces /status from RuntimeCommandPlugin"
  - "defer() + followup.send() pattern for 5-second timeout avoidance"
  - "format_status_embed returns plain string with Discord markdown code blocks"
metrics:
  duration: 2min
  completed: "2026-03-12T00:00:00Z"
---

# Phase 6 Plan 02: Discord /status 커맨드 Summary

StatusCommandPlugin with format_status_embed — positions, daily PnL, strategy status counts in one response.

## What Was Built

### Task 1: StatusCommandPlugin + format_status_embed
- `format_status_embed(control, lifecycle)` — runtime info, open positions with PnL%, daily realized PnL, strategy status counts
- `StatusCommandPlugin` with defer()/followup.send() pattern
- Moved /status from RuntimeCommandPlugin to StatusCommandPlugin
- Updated `__init__.py` DEFAULT_COMMAND_PLUGINS
- 7 unit tests covering positions, PnL, strategy counts, runtime, edge cases
- **Commit:** 9757320

### Task 2: Edge cases and PnL accuracy
- TradeSide.long/short enum alignment verified
- Empty positions/executions/strategies handled gracefully
- **Commit:** 9757320 (combined with task 1)

## Deviations from Plan

- Tasks 1 and 2 combined into single commit due to tight coupling.

## Verification

```
tests/test_status_command.py -- 7 passed
```

## Self-Check: PASSED

- FOUND: engine/interfaces/discord/commands/status.py
- FOUND: tests/test_status_command.py
- FOUND: 9757320 (Tasks 1+2)

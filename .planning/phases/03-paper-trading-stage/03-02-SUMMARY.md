---
phase: 03-paper-trading-stage
plan: 02
subsystem: strategy
tags: [promotion-gate, sharpe, lifecycle, discord, fastapi, rich-cli, pydantic]

# Dependency graph
requires:
  - phase: 03-paper-trading-stage/03-01
    provides: PaperBalance, PaperPnlSnapshot, PaperRepository, TradeRepository
provides:
  - PromotionGate with 6-criteria evaluation (days/trades/sharpe/win_rate/DD/PnL)
  - resolve_promotion_config 3-level merge (code < global < strategy)
  - LifecycleManager paper->active gate enforcement
  - CLI paper_cli (status/detail/promotion readiness)
  - REST API /paper/status, /paper/promotion/{id}
  - Discord /페이퍼현황, /전략승격 with PromotionConfirmView
affects: [04-portfolio-risk, 05-performance-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns: [promotion-gate-evaluation, 3-level-config-merge, confirm-view-button-pattern]

key-files:
  created:
    - engine/strategy/promotion_gate.py
    - engine/backtest/paper_cli.py
    - api/routers/paper.py
    - engine/interfaces/discord/commands/paper_trading.py
    - tests/test_promotion_gate.py
    - tests/test_paper_discord.py
  modified:
    - engine/strategy/lifecycle_manager.py
    - engine/schema.py
    - engine/interfaces/discord/commands/__init__.py
    - api/routers/__init__.py

key-decisions:
  - "LifecycleManager.transition() paper->active requires gate/gate_config/session params -- other transitions unaffected"
  - "Sharpe skip when < 2 daily data points (passed=True) -- insufficient data should not block"
  - "Max DD comparison: actual >= threshold (both negative) -- -0.10 >= -0.20 means OK"
  - "PromotionConfirmView timeout 120s -- longer than TransitionConfirmView (60s) for promotion decision"

patterns-established:
  - "PromotionGate evaluate pattern: fetch data -> run checks -> aggregate -> estimate"
  - "3-level config merge: code defaults < global_config < strategy_def override"
  - "Discord PromotionConfirmView: evaluate first, show button only if passed"

requirements-completed: [LIFE-03]

# Metrics
duration: 8min
completed: 2026-03-11
---

# Phase 3 Plan 02: Promotion Gate + 3-Channel Interface Summary

**PromotionGate with 6-criteria evaluation (Sharpe/win_rate/DD/days/trades/PnL), LifecycleManager gate enforcement on paper->active, and CLI/API/Discord 3-channel paper performance interface**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-11T14:59:39Z
- **Completed:** 2026-03-11T15:07:39Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- PromotionGate evaluates 6 criteria with 3-level config merge (code < global < strategy override)
- LifecycleManager enforces gate passage on paper->active transition -- no gate means rejection
- CLI (Rich table), REST API (3 endpoints), Discord (/페이퍼현황 + /전략승격) all operational
- 30 tests covering gate logic, config merge, lifecycle integration, embed builders, plugin registration

## Task Commits

Each task was committed atomically:

1. **Task 1: PromotionGate domain logic + LifecycleManager integration + StrategyDefinition extension** - `388824c` (feat)
2. **Task 2: Paper performance 3-channel interface (CLI + API + Discord)** - `f21472d` (feat)

## Files Created/Modified
- `engine/strategy/promotion_gate.py` - PromotionGate, PromotionConfig, PromotionResult, resolve_promotion_config
- `engine/strategy/lifecycle_manager.py` - gate/gate_config/session params on transition(), paper->active enforcement
- `engine/schema.py` - StrategyDefinition.promotion_gates optional field
- `engine/backtest/paper_cli.py` - Rich table CLI: show_paper_status, show_paper_detail, show_promotion_readiness
- `api/routers/paper.py` - GET /paper/status, /status/{id}, /promotion/{id} with Pydantic response models
- `engine/interfaces/discord/commands/paper_trading.py` - PaperTradingPlugin with /페이퍼현황, /전략승격, PromotionConfirmView
- `engine/interfaces/discord/commands/__init__.py` - PaperTradingPlugin registered in DEFAULT_COMMAND_PLUGINS
- `api/routers/__init__.py` - paper router registered
- `tests/test_promotion_gate.py` - 19 tests for gate logic, config merge, lifecycle integration
- `tests/test_paper_discord.py` - 11 tests for embed builders, plugin registration, imports

## Decisions Made
- LifecycleManager.transition() paper->active requires gate/gate_config/session params -- other transitions backward compatible
- Sharpe check skipped (passed=True) when < 2 daily data points -- insufficient data should not block promotion
- Max DD comparison uses actual >= threshold (both negative values) -- -0.10 >= -0.20 means acceptable
- PromotionConfirmView timeout 120s (vs TransitionConfirmView 60s) -- promotion is a higher-stakes decision

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing test failure in test_broker.py::TestUpbitBroker (missing upbit_broker module) -- unrelated to this plan, out of scope

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 3 complete: PaperBroker persistence (Plan 01) + Promotion Gate (Plan 02) both operational
- Ready for Phase 4 (Portfolio Risk): LifecycleManager + PromotionGate provide the foundation for multi-strategy risk management
- All LIFE-03 requirements satisfied

## Self-Check: PASSED

All 10 files verified on disk. Both task commits (388824c, f21472d) confirmed in git log.

---
*Phase: 03-paper-trading-stage*
*Completed: 2026-03-11*

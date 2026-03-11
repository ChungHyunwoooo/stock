---
phase: 02-backtest-quality-gates
plan: 01
subsystem: backtest
tags: [slippage, fee-model, depth-cache, ccxt, parquet, protocol, dataclass]

# Dependency graph
requires:
  - phase: 01-lifecycle-foundation
    provides: BacktestRunner, StrategyDefinition, registry infrastructure
provides:
  - SlippageModel Protocol (NoSlippage, VolumeAdjustedSlippage)
  - DepthCache Parquet read/write for orderbook depth statistics
  - OrderbookDepthCollector via ccxt REST fetch_order_book
  - FeeModel with JSON config loader (exchange_fees.json)
  - ValidationResult + WindowResult shared dataclasses
  - BacktestRunner slippage+fee injection (backward compatible)
affects: [02-02 WalkForward, 02-03 CPCV, 02-04 MultiSymbol, 02-05 DB persistence]

# Tech tracking
tech-stack:
  added: []
  patterns: [SlippageModel Protocol injection, Parquet depth cache with TTL, JSON fee config]

key-files:
  created:
    - engine/backtest/slippage.py
    - engine/backtest/fee_model.py
    - engine/backtest/validation_result.py
    - engine/data/depth_cache.py
    - engine/data/depth_collector.py
    - config/exchange_fees.json
    - tests/test_slippage.py
    - tests/test_backtest_costs.py
  modified:
    - engine/backtest/runner.py

key-decisions:
  - "SlippageModel as Protocol with calculate_slippage(symbol, side, order_size_usd, price) -> float"
  - "DepthCache uses single Parquet file with TTL expiration, not per-symbol files"
  - "Fee deducted as capital * fee_rate on entry and exit (proportional to capital)"
  - "BacktestRunner backward compatible: no-arg constructor defaults to NoSlippage + fee_rate=0.0"

patterns-established:
  - "SlippageModel Protocol: Port/Adapter injection for cost models in BacktestRunner"
  - "DepthCache: Parquet-based depth statistics with TTL (mirrors ohlcv_cache pattern)"
  - "JSON fee config: config/exchange_fees.json for exchange-specific maker/taker rates"

requirements-completed: [BT-01]

# Metrics
duration: 5min
completed: 2026-03-11
---

# Phase 2 Plan 01: SlippageModel + DepthCache + FeeModel + BacktestRunner Cost Integration Summary

**SlippageModel Protocol with VolumeAdjustedSlippage (depth-based) + FeeModel (JSON config) injected into BacktestRunner, proving cost application lowers returns**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-11T09:09:12Z
- **Completed:** 2026-03-11T09:14:15Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- SlippageModel Protocol with NoSlippage (zero cost) and VolumeAdjustedSlippage (depth-proportional) implementations
- DepthCache reads/writes orderbook depth statistics from Parquet with TTL expiration; OrderbookDepthCollector fetches via ccxt REST
- FeeModel loads exchange-specific maker/taker rates from config/exchange_fees.json with fallback defaults
- BacktestRunner integrates slippage+fee at entry/exit prices, backward compatible with no-arg constructor
- ValidationResult + WindowResult shared dataclasses ready for WF/CPCV plans
- 21 tests (15 unit + 6 integration) all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: DepthCache + DepthCollector + SlippageModel + FeeModel + ValidationResult + tests** - `9754cab` (feat)
2. **Task 2: BacktestRunner slippage+fee integration + tests** - `cd4e487` (feat)

_Both tasks followed TDD: RED (failing tests) -> GREEN (implementation) -> verify_

## Files Created/Modified
- `engine/backtest/slippage.py` - SlippageModel Protocol + NoSlippage + VolumeAdjustedSlippage
- `engine/backtest/fee_model.py` - FeeModel JSON loader + get_fee_rate with defaults
- `engine/backtest/validation_result.py` - WindowResult + ValidationResult dataclasses
- `engine/data/depth_cache.py` - DepthCache Parquet read/write with TTL
- `engine/data/depth_collector.py` - OrderbookDepthCollector via ccxt REST
- `config/exchange_fees.json` - Binance (spot/futures) + Upbit (spot) fee rates
- `engine/backtest/runner.py` - Modified: slippage_model + fee_rate injection in __init__ and _simulate
- `tests/test_slippage.py` - 15 tests for DepthCache, Collector, Slippage, FeeModel, ValidationResult
- `tests/test_backtest_costs.py` - 6 tests for BacktestRunner cost integration

## Decisions Made
- SlippageModel Protocol with 4 params (symbol, side, order_size_usd, price) -- matches RESEARCH.md Pattern 1
- DepthCache uses single consolidated Parquet file per cache_dir (simpler than per-symbol files)
- Fee applied as capital * fee_rate (proportional) rather than fixed amount -- scales naturally with position size
- validation_result.py pre-existed with `slots=True` -- compatible with plan, no modification needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing test failures in `tests/test_broker.py::TestUpbitBroker` (missing upbit_broker module) and `tests/test_walk_forward.py` (unrelated to this plan) -- documented as out of scope

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- SlippageModel + FeeModel ready for use by all subsequent plans
- ValidationResult interface ready for Plan 02 (WalkForward) and Plan 03 (CPCV)
- DepthCache + DepthCollector ready for production depth data collection
- BacktestRunner cost injection verified with 21 passing tests

## Self-Check: PASSED

- All 9 files verified present
- Commit 9754cab verified
- Commit cd4e487 verified
- 21/21 new tests passing
- 288 existing tests passing (2 pre-existing failures excluded)

---
*Phase: 02-backtest-quality-gates*
*Completed: 2026-03-11*

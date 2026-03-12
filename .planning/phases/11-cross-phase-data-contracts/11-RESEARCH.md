# Phase 11: Cross-Phase Data Contracts - Research

**Researched:** 2026-03-12
**Domain:** PromotionGate backtest baseline comparison + CPCV sweep integration
**Confidence:** HIGH

## Summary

Phase 11 connects two previously independent subsystems: (1) the PromotionGate (Phase 3) needs to cross-reference BacktestRepository Sharpe as a baseline when evaluating paper-to-live promotion, and (2) the IndicatorSweeper (Phase 7) needs a CPCV validation mode alongside the existing WalkForwardValidator.

Both tasks are well-scoped integration work. The modules already exist with clean interfaces -- CPCVValidator and WalkForwardValidator share identical `validate(equity_curve) -> ValidationResult` signatures, and BacktestRepository already has `get_history()` used by PerformanceMonitor for the same baseline pattern. The core challenge is bridging the strategy_id type gap (string in PromotionGate/registry vs int FK in BacktestRecord) and adding a validation_mode switch to SweepConfig/IndicatorSweeper.

**Primary recommendation:** Follow the existing PerformanceMonitor pattern for backtest baseline lookup, and use a string config field on SweepConfig to toggle WalkForward vs CPCV in the objective function.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LIFE-03 | Paper->Live 승격 시 Sharpe/승률/기간/최대DD 기준을 자동 검증하고, 미충족 시 승격을 차단한다 | PromotionGate.evaluate() already checks 6 criteria including Sharpe from paper snapshots. Enhancement: add backtest baseline Sharpe comparison check. BacktestRepository.get_history() pattern already proven in PerformanceMonitor. |
| BT-05 | CPCV(Combinatorial Purged Cross-Validation)로 walk-forward를 고도화할 수 있다 | CPCVValidator already implemented with identical interface to WalkForwardValidator. Integration point: IndicatorSweeper._objective() needs mode switch to select validator. SweepConfig needs validation_mode field. |
</phase_requirements>

## Architecture Patterns

### Current Data Flow (PromotionGate)

```
PaperPnlSnapshot (daily_pnl, equity) --> PromotionGate.evaluate()
    - days check
    - trade count check
    - win rate check
    - Sharpe (from paper daily_pnl)  <-- PAPER-ONLY, no backtest comparison
    - max drawdown (from paper equity)
    - cumulative PnL
```

### Target Data Flow (LIFE-03: Backtest Baseline Comparison)

```
PaperPnlSnapshot --> PromotionGate.evaluate()
    - ... existing 6 checks ...
    - NEW: backtest_sharpe check (paper Sharpe < backtest Sharpe --> block)

BacktestRepository.get_history(session, strategy_id) --> baseline Sharpe
```

### Key Design Constraint: strategy_id Type Mismatch

- **PromotionGate** uses `strategy_id: str` (registry name like "auto_rsi_3f1815")
- **BacktestRecord** uses `strategy_id: int` (FK to strategies.id)
- **PerformanceMonitor._get_baseline()** already passes string strategy_id to `get_history()` -- this works because SQLAlchemy coerces, but it is fragile

**Resolution pattern:** Follow PerformanceMonitor's approach -- pass the strategy_id (str) and let the caller handle the lookup. The PromotionGate should accept an optional `BacktestRepository` and resolve the baseline independently. If no backtest exists, the check passes (same as Sharpe skip when < 2 data points).

### Target Data Flow (BT-05: CPCV in Sweep)

```
IndicatorSweeper._objective()
    - BacktestRunner.run() --> equity_curve
    - IF validation_mode == "cpcv":
        CPCVValidator.validate(equity_curve)
      ELSE:
        WalkForwardValidator.validate(equity_curve)
    - MultiSymbolValidator.validate()
```

### Recommended Project Structure (changes only)

```
engine/
  strategy/
    promotion_gate.py      # Add BacktestRepository dependency + baseline check
    indicator_sweeper.py   # Add CPCV mode branch in _objective()
    sweep_config.py        # Add validation_mode field
```

### Pattern: Validator Mode Switch

**What:** SweepConfig gets a `validation_mode: str = "walk_forward"` field. IndicatorSweeper._objective() instantiates the correct validator based on this field.

**When to use:** When two validators share the same interface and the choice is configuration-driven.

**Example:**
```python
# In SweepConfig
validation_mode: str = "walk_forward"  # "walk_forward" | "cpcv"

# In IndicatorSweeper._objective()
if self._config.validation_mode == "cpcv":
    from engine.backtest.cpcv import CPCVValidator
    validator = CPCVValidator(gap_threshold=self._config.wf_gap_threshold)
else:
    validator = WalkForwardValidator(gap_threshold=self._config.wf_gap_threshold)
vr = validator.validate(result.equity_curve)
```

### Pattern: Optional Baseline Comparison in PromotionGate

**What:** PromotionGate accepts an optional BacktestRepository + session. If provided, it adds a 7th check comparing paper Sharpe against backtest baseline Sharpe. If no backtest record exists, the check passes (graceful degradation).

**Example:**
```python
class PromotionGate:
    def __init__(
        self,
        paper_repo: PaperRepository,
        trade_repo: TradeRepository,
        backtest_repo: BacktestRepository | None = None,  # NEW
    ) -> None:
        ...

    def evaluate(self, strategy_id, config, session) -> PromotionResult:
        # ... existing 6 checks ...

        # 7. Backtest baseline Sharpe comparison
        if self.backtest_repo is not None and sharpe is not None:
            baseline = self._get_backtest_sharpe(session, strategy_id)
            if baseline is not None:
                passed = sharpe >= baseline
                checks["backtest_sharpe"] = PromotionCheck(
                    name="백테스트 대비 Sharpe",
                    required=baseline,
                    actual=sharpe,
                    passed=passed,
                )
```

### Anti-Patterns to Avoid

- **Hard-coding strategy_id resolution:** Do not add a StrategyRepository lookup inside PromotionGate to convert name->id. Let the caller resolve or use the existing pattern where string IDs work.
- **Coupling CPCVValidator parameters to SweepConfig:** Keep CPCV-specific params (n_folds, n_test_folds, purged_size) as CPCVValidator defaults. SweepConfig only needs validation_mode + gap_threshold.
- **Breaking backward compatibility:** PromotionGate constructor and IndicatorSweeper._objective() must remain backward compatible with existing callers.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CPCV split logic | Custom fold generator | skfolio CombinatorialPurgedCV | Already used in engine/backtest/cpcv.py |
| Sharpe computation | New calculator | engine.backtest.metrics.compute_sharpe_ratio | Existing, tested |
| Backtest baseline lookup | New query method | BacktestRepository.get_history(session, id, limit=1) | Already exists, used by PerformanceMonitor |

## Common Pitfalls

### Pitfall 1: strategy_id Type Confusion
**What goes wrong:** BacktestRecord.strategy_id is an int FK, but PromotionGate works with string strategy_id from registry.
**Why it happens:** Two different ID systems -- registry (string name) vs DB (integer PK).
**How to avoid:** The backtest baseline lookup needs a strategy name -> strategy_id (int) resolution step, OR the check should accept the backtest Sharpe as a pre-resolved parameter. PerformanceMonitor already does `get_history(session, strategy_id)` passing a string -- follow that pattern but be aware it relies on SQLAlchemy coercion.
**Warning signs:** Tests pass with mock but fail with real SQLite because type coercion behaves differently.

### Pitfall 2: Missing Backtest Data
**What goes wrong:** New strategies have no backtest records. If the baseline check requires a backtest, all new strategies are blocked from promotion.
**Why it happens:** Backtest records are created by BacktestRunner with auto_save=True, but sweep-created strategies may not have DB records.
**How to avoid:** If no backtest record exists, skip the baseline check (passed=True). Same pattern as Sharpe skip when < 2 data points.

### Pitfall 3: CPCV Equity Curve Length
**What goes wrong:** CPCVValidator requires `n_folds * 10` minimum data points (default 60). Short backtest periods in sweep may trigger ValueError.
**Why it happens:** CPCV needs more data than walk-forward due to combinatorial splitting.
**How to avoid:** Catch ValueError in _objective() and return -inf (same as WF failure). Or check length before calling validate.

### Pitfall 4: Annualization Mismatch
**What goes wrong:** PromotionGate computes Sharpe from daily PnL (sqrt(365)), BacktestRecord.sharpe_ratio comes from equity curve pct_change (sqrt(252) in compute_sharpe_ratio). Different annualization factors make comparison invalid.
**Why it happens:** Paper uses calendar days (365), backtest uses trading days (252).
**How to avoid:** Use the same annualization factor for both. Either normalize paper Sharpe to 252, or document the comparison as approximate. The simplest approach: re-compute backtest Sharpe from result_json if available, using the same formula as paper.

### Pitfall 5: Aggregate Check Change
**What goes wrong:** Adding a 7th check changes the `all(c.passed for c in checks.values())` aggregation, potentially blocking promotions that previously passed.
**Why it happens:** The new check is included in the aggregate by default.
**How to avoid:** The check should only be included when backtest_repo is provided AND a baseline exists. If the check is skipped (no baseline), it should not appear in the checks dict at all, preserving backward compatibility.

## Code Examples

### Existing: PerformanceMonitor Baseline Lookup (proven pattern)
```python
# Source: engine/strategy/performance_monitor.py:103-121
def _get_baseline(self, session, strategy_id):
    records = self.backtest_repo.get_history(session, strategy_id, limit=1)
    if not records:
        return None, None
    record = records[0]
    sharpe = record.sharpe_ratio
    win_rate = None
    try:
        result = json.loads(record.result_json)
        win_rate = result.get("win_rate")
    except (json.JSONDecodeError, TypeError):
        pass
    return sharpe, win_rate
```

### Existing: WalkForward/CPCV Shared Interface (proven pattern)
```python
# Both return ValidationResult with identical interface
wf = WalkForwardValidator(gap_threshold=0.5)
wf_result = wf.validate(equity_curve)  # -> ValidationResult

cpcv = CPCVValidator(gap_threshold=0.5)
cpcv_result = cpcv.validate(equity_curve)  # -> ValidationResult
```

### Existing: PromotionGate Sharpe Skip Pattern
```python
# Source: engine/strategy/promotion_gate.py:155-159
checks["sharpe"] = PromotionCheck(
    name="Sharpe Ratio",
    required=config.min_sharpe,
    actual=round(sharpe, 4) if sharpe is not None else None,
    passed=(sharpe is not None and sharpe >= config.min_sharpe) if sharpe is not None else True,
)
# None actual -> passed=True (skip pattern)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Paper Sharpe only | Paper vs Backtest baseline | Phase 11 | Catches strategies that degrade from backtest performance |
| WalkForward only in sweep | WF or CPCV selectable | Phase 11 | CPCV provides statistically stronger overfit detection |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | pyproject.toml or pytest.ini (if exists) |
| Quick run command | `.venv/bin/python -m pytest tests/test_promotion_gate.py tests/test_cpcv.py tests/test_indicator_sweeper.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFE-03 | PromotionGate blocks when paper Sharpe < backtest baseline | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py -x -k backtest_sharpe` | Wave 0 |
| LIFE-03 | PromotionGate skips baseline check when no backtest exists | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py -x -k no_backtest` | Wave 0 |
| BT-05 | IndicatorSweeper uses CPCV when validation_mode=cpcv | unit | `.venv/bin/python -m pytest tests/test_indicator_sweeper.py -x -k cpcv` | Wave 0 |
| BT-05 | SweepConfig.from_dict parses validation_mode field | unit | `.venv/bin/python -m pytest tests/test_indicator_sweeper.py -x -k validation_mode` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_promotion_gate.py tests/test_cpcv.py tests/test_indicator_sweeper.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_promotion_gate.py::TestPromotionGateEvaluate::test_backtest_sharpe_*` -- new tests for LIFE-03 baseline comparison
- [ ] `tests/test_indicator_sweeper.py::TestObjective*::test_*cpcv*` -- new tests for BT-05 CPCV mode

## Open Questions

1. **Annualization factor alignment**
   - What we know: PromotionGate uses sqrt(365), compute_sharpe_ratio uses sqrt(252)
   - What's unclear: Whether the comparison should be exact or approximate
   - Recommendation: Use the same factor. The simplest fix is to use 252 in PromotionGate when comparing against backtest, since backtest data uses trading-day frequency. Document the choice.

2. **strategy_id resolution for backtest lookup**
   - What we know: BacktestRecord.strategy_id is int FK, registry uses string names
   - What's unclear: Whether all sweep-registered strategies get a StrategyRecord in DB
   - Recommendation: Accept an optional `backtest_sharpe: float | None` parameter in evaluate() as an alternative to repository lookup. This sidesteps the type mismatch entirely and lets the caller resolve.

## Sources

### Primary (HIGH confidence)
- `engine/strategy/promotion_gate.py` -- Current PromotionGate implementation, 6 checks
- `engine/strategy/indicator_sweeper.py` -- Current sweep pipeline with WalkForward only
- `engine/backtest/cpcv.py` -- CPCVValidator with identical interface to WalkForwardValidator
- `engine/backtest/walk_forward.py` -- WalkForwardValidator interface reference
- `engine/strategy/performance_monitor.py` -- BacktestRepository baseline lookup pattern
- `engine/core/repository.py` -- BacktestRepository.get_history() API
- `engine/core/db_models.py` -- BacktestRecord schema (strategy_id: int FK)
- `engine/strategy/sweep_config.py` -- SweepConfig current fields
- `engine/backtest/validation_result.py` -- Shared ValidationResult/WindowResult models

### Secondary (MEDIUM confidence)
- `tests/test_promotion_gate.py` -- Existing test patterns and fixtures
- `tests/test_indicator_sweeper.py` -- Existing sweep test patterns with mocks
- `tests/test_cpcv.py` -- CPCVValidator test coverage

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all modules already exist, interfaces are clear
- Architecture: HIGH -- patterns proven by PerformanceMonitor and existing validator interface
- Pitfalls: HIGH -- identified from direct code reading (type mismatch, annualization, data absence)

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable internal codebase)

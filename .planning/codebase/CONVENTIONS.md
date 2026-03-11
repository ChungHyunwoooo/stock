# Coding Conventions

**Analysis Date:** 2026-03-11

## Naming Patterns

**Files:**
- Suffix encodes role: `_detector`, `_evaluator`, `_scanner`, `_cache`, `_broker`, `_runner`, `_store`
- Prefix encodes subject: `upbit_`, `binance_`, `discord_`, `scalping_`, `pattern_`, `spike_`
- One concept per file: `scalping_risk.py`, `condition_evaluator.py`, `pattern_detector.py`
- Private helpers use leading underscore: `_find_next_resistance`, `_calc_long_tp`, `_make_v_shape`

**Directories:**
- Plural concept names: `indicators/`, `patterns/`, `strategies/`, `notifications/`, `interfaces/`
- Sub-grouping by domain: `indicators/momentum/`, `indicators/price/`, `indicators/volume/`

**Functions:**
- Verb prefix by operation type:
  - `calc_` — pure numerical computation: `calc_atr`, `calc_atr_percentile`
  - `detect_` — pattern recognition: `detect_double_bottom`, `detect_asc_triangle`
  - `evaluate_` — condition logic: `evaluate_condition`, `evaluate_condition_group`
  - `find_` — search/lookup: `find_local_extrema`, `_find_next_resistance`
  - `fetch_` — external data retrieval: `fetch_balance`, `fetch_total_equity`
  - `build_` — object construction: `_build_execution_record`
  - `calculate_` — compound computation: `calculate_dynamic_sl_tp`, `calculate_scalp_risk`
  - `scan_` — batch iteration: `scan_patterns`
- Internal helpers prefixed with `_`: `_validate_order`, `_normalize_balance`, `_place_order`

**Variables and Parameters:**
- `snake_case` throughout
- Descriptive, domain-specific: `atr_pctile`, `sl_mult_min`, `leverage_max`, `entry_price`
- Constants: `UPPER_SNAKE_CASE` at module level: `_MIN_PEAK_SEPARATION = 10`, `_SL_MARGIN = 0.002`
- Private module-level constants use leading underscore: `_MIN_RR`, `_TP_FALLBACK_RATIO`

**Classes:**
- PascalCase: `PatternSignal`, `ScalpRiskConfig`, `ScalpRiskResult`, `BaseBroker`
- Enums inherit `(str, Enum)` pattern: `TradingMode`, `SignalAction`, `TradeSide`, `BrokerKind`
- Pydantic models for external schemas: `StrategyDefinition`, `IndicatorDef`, `Condition`
- Dataclasses for internal domain objects: `PatternSignal`, `ScalpRiskConfig`, `ExecutionRecord`

**Domain Vocabulary (use these terms, not alternatives):**
- `indicator` — calculated number (not "metric" or "signal")
- `pattern` — structural recognition result (not "formation")
- `signal` — trading decision output (not "recommendation")
- `alert` — user notification (not "message")

## Code Style

**Formatting:**
- Tool: `ruff` (configured in `pyproject.toml`)
- Line length: 100 characters
- Target: Python 3.11+

**Linting (ruff rules active):**
- `E` — pycodestyle errors
- `F` — pyflakes (unused imports, undefined names)
- `I` — isort (import ordering)
- `N` — pep8-naming
- `W` — pycodestyle warnings

## Import Organization

**Header pattern (always in this order):**
1. `from __future__ import annotations` — first line in virtually all modules (91 files)
2. Standard library: `logging`, `dataclasses`, `datetime`, `abc`, `uuid`, `threading`
3. Third-party: `numpy`, `pandas`, `pydantic`, `sqlalchemy`, `ccxt`
4. Internal: `from engine.core.models import ...`, `from engine.schema import ...`

**Example from `engine/strategy/scalping_risk.py`:**
```python
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.schema import RiskParams
from engine.strategy.risk import calculate_position_size
```

**No path aliases** — absolute imports from `engine.*` and `api.*` roots only.

## Section Separators

Horizontal dividers in Korean mark logical sections within files:
```python
# ── ATR ──────────────────────────────────────────────────────
# ── 동적 SL/TP ──────────────────────────────────────────────
# ---------------------------------------------------------------------------
# 지지·저항 기반 SL/TP 헬퍼
# ---------------------------------------------------------------------------
```

Both `# ──` (short) and `# ---` (long, 75-char) styles are used; either is acceptable. Use separators when a file has 3+ distinct logical sections.

## Data Model Patterns

**Two model layers:**

1. **Pydantic `BaseModel`** — external-facing schemas, JSON I/O, strategy definitions:
   - `engine/schema.py`: `StrategyDefinition`, `IndicatorDef`, `Condition`, `ConditionGroup`, `RiskParams`
   - Use `Field(...)` with `description=` for documentation

2. **`@dataclass(slots=True)`** — internal runtime objects, performance-sensitive:
   - `engine/core/models.py`: `TradingSignal`, `OrderRequest`, `ExecutionRecord`, `Position`
   - `engine/strategy/pattern_detector.py`: `PatternSignal`
   - `engine/strategy/scalping_risk.py`: `ScalpRiskConfig`, `ScalpRiskResult`
   - `slots=True` is the default for new dataclasses (memory + speed)
   - `frozen=True` added when immutability is needed: `@dataclass(frozen=True, slots=True)`

**Enums always inherit `(str, Enum)`:**
```python
class TradingMode(str, Enum):
    alert_only = "alert_only"
    semi_auto = "semi_auto"
    auto = "auto"
```
This enables both `TradingMode.auto` and `"auto"` comparisons and JSON serialization.

## Error Handling

**Strategy:**
- Validate at boundaries, not deep in logic
- Raise typed exceptions from validation: `raise ValueError(f"수량은 0보다 커야 합니다: {order.quantity}")`
- In long-running loops and scanner code, catch broadly and log, then continue:
  ```python
  except Exception as e:
      logger.error("...: %s", e)
  ```
- CLI layer catches exceptions, logs, then calls `raise typer.Exit(1)` — never swallows silently
- Abstract base classes raise `NotImplementedError` or use `@abstractmethod` with `...` body

**Validation location:** `BaseBroker._validate_order()` validates before API call; Pydantic validates at schema boundary.

## Logging

**Framework:** Python stdlib `logging`

**Setup pattern (every module that logs):**
```python
logger = logging.getLogger(__name__)
```
37 engine modules use this pattern. All use `__name__` — never a custom string.

**Format used in log calls:**
```python
logger.info(
    "[%s] %s %s %s qty=%.6f price=%.2f → %s",
    self.exchange_name, order.action.value, order.side.value,
    order.symbol, order.quantity, order.price, result.status,
)
```
- Use `%` formatting (not f-strings) in log calls
- Bracket prefix `[exchange_name]` for broker/exchange-scoped messages
- Numeric format: `%.6f` for quantities, `%.2f` for prices

**Log levels:**
- `logger.info` — normal execution events (order placed, signal processed)
- `logger.error` — recoverable errors in loops
- `logger.warning` — unexpected but non-fatal state

## Comments

**Module docstrings:** Every module has a top-level triple-quoted docstring explaining purpose, patterns used, and key design decisions. Korean is acceptable in docstrings.

**Inline comments:** Korean used freely for domain explanation; English used for code mechanics. Both are acceptable.

**Function docstrings:** Short one-liners for most functions. Only complex functions get multi-line docstrings.

**Test docstrings:** One-line docstrings on test functions describing the scenario being tested (Korean acceptable):
```python
def test_crosses_above_numeric(df):
    """col_a crosses above 30 when it moves from <=30 to >30 (index 2)."""
```

## Function Design

**Size:** Functions are kept small and single-purpose. Files exceeding 300 lines are candidates for splitting.

**Parameters:** Use keyword arguments for config objects. Pass `pd.DataFrame` and `np.ndarray` by reference (not copied).

**Return Values:**
- Pure computations return typed values: `float | None`, `tuple[list[int], list[int]]`
- State-mutating methods return `None` or the mutated object
- Domain results returned as dataclass instances: `ScalpRiskResult`, `PatternSignal`
- `None` returned when detection fails (not exceptions): `detect_double_bottom` returns `PatternSignal | None`

## Abstract Base Class Pattern

```python
class BaseBroker(ABC):
    exchange_name: str = "base"   # class-level defaults

    def execute_order(self, order, state) -> ExecutionRecord:
        """Template method — calls abstract hooks."""
        self._validate_order(order)
        result = self._place_order(order, converted_symbol)  # abstract
        ...

    @abstractmethod
    def _place_order(self, order, converted_symbol) -> ExecutionRecord: ...

    @abstractmethod
    def _fetch_raw_balance(self) -> dict[str, Any]: ...
```
Abstract methods use `...` as body (not `pass`). Template methods implement the common flow and call abstract hooks for exchange-specific behavior.

## Module Design

**Exports:** No barrel `__init__.py` re-exports at the `engine/` level — import directly from submodules.

**`__init__.py` files:** Minimal or empty. Some re-export key symbols for convenience (e.g., `engine/core/__init__.py`, `engine/execution/__init__.py`).

---

*Convention analysis: 2026-03-11*

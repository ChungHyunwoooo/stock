# Testing Patterns

**Analysis Date:** 2026-03-11

## Test Framework

**Runner:**
- pytest 8.0+
- Config: `pyproject.toml` (`[tool.pytest.ini_options]`)

**Assertion Library:**
- pytest built-in `assert`
- `pd.testing.assert_series_equal` for pandas comparisons
- `pytest.approx` for floating-point comparisons

**Run Commands:**
```bash
.venv/bin/python -m pytest          # Run all tests
.venv/bin/python -m pytest tests/   # Explicit testpath
.venv/bin/python -m pytest tests/test_scalping_risk.py  # Single file
.venv/bin/python -m pytest -k "TestCalcATR"             # Single class
```

**Async support:**
- `pytest-asyncio>=0.23.0` installed
- `asyncio_mode = "auto"` in `pyproject.toml` — no `@pytest.mark.asyncio` decorator needed

**HTTP mocking:**
- `httpx>=0.27.0` available for async HTTP client testing

## Test File Organization

**Location:** All tests in `tests/` directory (separate from source). No co-located test files.

**Naming:**
- Files: `test_{subject}.py` — e.g., `test_scalping_risk.py`, `test_pattern_detector.py`
- Sub-grouping by domain: `tests/trading/` for orchestration/application layer tests
- Non-test scripts in `tests/`: `spike_param_sweep.py`, `strategy_backtest_90d.py` (research scripts, not run by pytest)

**Structure:**
```
tests/
├── conftest.py                     # Shared fixtures (sample_df, sample_strategy, talib stub)
├── test_broker.py                  # Broker layer tests
├── test_candle_patterns.py
├── test_condition.py
├── test_confluence.py
├── test_ohlcv_cache.py
├── test_pattern_detector.py
├── test_pullback_detector.py
├── test_scalping_ema_crossover.py
├── test_scalping_risk.py
├── test_scalping_runner.py
├── test_schema.py
├── test_spike_detector_backtest.py
├── test_trade_repository.py
└── trading/
    ├── test_alert_presentation.py
    ├── test_analysis_chart.py
    ├── test_analysis_report.py
    ├── test_discord_autocomplete.py
    ├── test_discord_chart_attachment.py
    ├── test_discord_timeframe_routing.py
    ├── test_monitor_service.py
    ├── test_orchestrator.py
    ├── test_plugin_registry.py
    ├── test_runtime_store.py
    ├── test_scanner_runtime.py
    ├── test_strategy_generator.py
    └── test_symbol_cache.py
```

**Total test functions:** 278 across 30 files.

## Test Structure

**Suite Organization — class-based grouping:**
```python
class TestCalcATR:
    def test_atr_returns_series(self):
        ...

    def test_atr_positive(self):
        ...

    def test_atr_higher_volatility(self):
        ...
```
Group tests by the function/feature being tested. Class name pattern: `Test{FunctionOrFeatureName}`.

**Flat functions also used** for simple cases or integration tests:
```python
def test_alert_only_mode_sends_notification_without_execution(tmp_path):
    ...
```

**Docstrings on test functions** describe the scenario (Korean acceptable):
```python
def test_crosses_above_numeric(df):
    """col_a crosses above 30 when it moves from <=30 to >30 (index 2)."""
```

## Fixtures

**Shared fixtures** in `tests/conftest.py`:
```python
@pytest.fixture
def sample_df() -> pd.DataFrame:
    """50-row OHLCV DataFrame with deterministic values."""
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100.0, 150.0, n)
    return pd.DataFrame(
        {"open": close * 0.99, "high": close * 1.02,
         "low": close * 0.98, "close": close, "volume": np.ones(n) * 1_000_000},
        index=idx,
    )

@pytest.fixture
def sample_strategy() -> StrategyDefinition:
    """Minimal single-indicator strategy for use in tests."""
    return StrategyDefinition(...)
```

**Local fixtures** defined in individual test files when scope is narrow:
```python
@pytest.fixture
def cache(tmp_path):
    return OHLCVCacheManager(cache_dir=tmp_path / "ohlcv")
```

**`tmp_path` fixture** (pytest built-in) used extensively for file-based tests (cache, DB, JSON store).

**talib stub** in `conftest.py` — stubs out `talib` if not installed so tests run in any environment:
```python
try:
    import talib as _talib_real
except ImportError:
    _talib_mock = MagicMock()
    sys.modules.setdefault("talib", _talib_mock)
    sys.modules.setdefault("talib.abstract", _talib_mock)
```

## Test Data Helpers

**Private helper functions** (prefixed `_make_`) build test data inline in test files:
```python
def _make_ohlcv(n: int = 50, base_price: float = 50000.0, volatility: float = 0.005) -> pd.DataFrame:
    """테스트용 OHLCV 생성."""
    np.random.seed(42)   # Always seed for reproducibility
    ...

def _make_double_bottom_ohlcv(n=80, m1=20, m2=45, ...) -> tuple[np.ndarray, ...]:
    """쌍바닥 패턴이 있는 OHLCV 생성."""
    ...
```

**Key conventions for test data:**
- Always use `np.random.seed(42)` when generating random data
- Build minimal data (50-100 rows is typical)
- Use `pd.date_range("2024-01-01", ...)` or `"2026-01-01"` as base dates
- OHLCV DataFrames always have columns: `open`, `high`, `low`, `close`, `volume`
- Use deterministic `np.linspace` or hand-crafted arrays when exact values matter

**Builder methods inside test classes** for reuse within a class:
```python
class TestDoubleTop:
    def _make_double_top_ohlcv(self, n=80, m1=20, m2=45, close_val=88.0):
        ...
```

## Mocking

**Framework:** `unittest.mock` — `MagicMock`, `patch`

**Exchange API mocking (decorator pattern):**
```python
@patch("engine.execution.binance_broker.ccxt.binance")
def test_binance_spot_buy(self, mock_ccxt):
    mock_exchange = MagicMock()
    mock_ccxt.return_value = mock_exchange
    mock_exchange.create_order.return_value = {"id": "order123", "status": "closed"}
    ...
```

**Spec-bound mocks** for type safety:
```python
@pytest.fixture
def mock_broker(self):
    """BinanceBroker MagicMock (spec 적용)."""
    broker = MagicMock(spec=BinanceBroker)
    broker._exchange = MagicMock()
    ...
    return broker
```

**Context manager patching** for multi-dependency tests:
```python
with patch("engine.execution.scalping_runner.create_broker", return_value=mock_broker), \
     patch("engine.execution.scalping_runner.init_db"):
    runner = ScalpingRunner(...)
```

**In-memory implementations** preferred over mocks for state-bearing objects:
- `PaperBroker` — real in-memory broker for execution tests
- `MemoryNotifier` — real in-memory notifier for notification tests
- `JsonRuntimeStore(tmp_path / "runtime.json")` — real store using `tmp_path`

**What to mock:**
- External exchange APIs (`ccxt.binance`, `pyupbit.Upbit`)
- Network calls and websockets
- `init_db` and other infra setup that needs real services

**What NOT to mock:**
- Domain logic (use real implementations)
- `pd.DataFrame` computation
- File I/O when `tmp_path` can be used instead

## Assertion Patterns

**Numeric equality:**
```python
assert result.stop_loss == pytest.approx(min_low * (1 - _SL_MARGIN))
assert tp == pytest.approx(105.0 + _TP_FALLBACK_RATIO * 5.0)
```

**Pandas Series equality:**
```python
pd.testing.assert_series_equal(result_col.astype(bool), result_num.astype(bool), check_names=False)
pd.testing.assert_series_equal(result, expected)
```

**Relational assertions for trading logic:**
```python
assert sig.stop_loss < sig.entry_price < sig.take_profit   # LONG
assert sig.stop_loss > sig.entry_price > sig.take_profit   # SHORT
assert result.leverage >= 2
assert 0.0 <= result.atr_pctile <= 1.0
```

**Constant verification tests** — pin public constants to prevent silent config drift:
```python
def test_constants(self):
    assert _MIN_PEAK_SEPARATION == 10
    assert _SL_MARGIN == pytest.approx(0.002)
    assert _MIN_RR == pytest.approx(1.0)
    assert _TP_FALLBACK_RATIO == pytest.approx(2.0)
```

**State-based assertions** for integration flows:
```python
assert len(state.executions) == 1
assert len(state.positions) == 1
assert state.positions[0].entry_price == 100.0
assert len(notifier.signals) == 1
```

## Coverage

**Requirements:** None enforced (no `--cov` flag in config).

**Implicit standard:** Tests cover public API, edge cases, and boundary conditions. Private helper `_` functions are tested when they have complex logic (e.g., `_find_next_resistance`, `_calc_long_tp`).

## Test Types

**Unit Tests (majority):**
- Scope: single function or method
- Files: `test_condition.py`, `test_scalping_risk.py`, `test_pattern_detector.py`, `test_ohlcv_cache.py`
- No external dependencies; all I/O through `tmp_path` or in-memory objects

**Integration Tests:**
- Scope: multi-component workflow
- Files: `test_integration.py`, `test_broker.py`, `test_scalping_runner.py`, `tests/trading/test_orchestrator.py`
- Use real domain objects wired together; mock only exchange APIs

**Backtest/Research Scripts (not pytest):**
- `tests/spike_param_sweep.py` — parameter sweep scripts
- `tests/strategy_backtest_90d.py` — 90-day backtest runner
- Run manually, not part of `pytest` suite

**E2E Tests:** Not present.

## Common Patterns

**Async Testing:**
```python
# asyncio_mode = "auto" in pyproject.toml means:
async def test_something():
    result = await some_async_function()
    assert result is not None
# No @pytest.mark.asyncio decorator needed
```

**Database Testing (SQLAlchemy in-memory):**
```python
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
# Use session in tests; destroy automatically on test end
```

**File System Testing:**
```python
def test_put_creates_parquet(self, cache, tmp_path):
    df = _make_ohlcv()
    cache.put("KRW-BTC", "1h", df)
    parquet_path = tmp_path / "ohlcv" / "KRW_BTC_1h.parquet"
    assert parquet_path.exists()
```

**Error Path Testing:**
```python
def test_no_detect_when_no_breakout(self):
    close, high, low = _make_double_bottom_ohlcv(close_val=95.0)  # 넥라인 미돌파
    sig = detect_double_bottom(close, high, low, len(close) - 1, low_mins, high_maxs)
    assert sig is None
```

**Monotonicity / ordering invariants:**
```python
def test_monotonic_decrease(self):
    """percentile 증가 → 레버리지 감소 (단조)."""
    leverages = [calculate_dynamic_leverage(0.5, p / 10) for p in range(11)]
    for i in range(len(leverages) - 1):
        assert leverages[i] >= leverages[i + 1]
```

**Boundary / clamping tests:**
```python
def test_sl_pct_clamping(self):
    cfg = ScalpRiskConfig(min_sl_pct=0.5, max_sl_pct=1.0)
    _, _, sl_pct, _ = calculate_dynamic_sl_tp(50000, 1, 0.5, "long", cfg)
    assert sl_pct >= cfg.min_sl_pct

    _, _, sl_pct, _ = calculate_dynamic_sl_tp(50000, 5000, 0.5, "long", cfg)
    assert sl_pct <= cfg.max_sl_pct
```

---

*Testing analysis: 2026-03-11*

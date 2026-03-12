# Phase 9: Production Wiring -- Orchestrator & Bootstrap - Research

**Researched:** 2026-03-12
**Domain:** Dependency injection / production wiring of existing components
**Confidence:** HIGH

## Summary

Phase 9 is a pure wiring phase -- no new algorithms or libraries. Three existing, fully-implemented components (PositionSizer, PortfolioRiskManager, StrategyPerformanceMonitor) must be connected into the production execution path (orchestrator + bootstrap). The codebase already has established patterns for constructor injection with None defaults, plugin registries, and try/except non-blocking error handling.

The key challenge is modifying `process_signal()` to replace the caller-provided `quantity` parameter with dynamically calculated sizing from PositionSizer, gated by PortfolioRiskManager allocation weights. The bootstrap must assemble all dependencies (repos, lifecycle, session_factory) for PerformanceMonitor and start its daemon thread.

**Primary recommendation:** Follow existing injection patterns exactly (None default + guard check). Make PositionSizer and PortfolioRiskManager mandatory (raise on None) per user decision. Wire PerformanceMonitor as optional daemon in bootstrap.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- PositionSizer.calculate() called inside process_signal() -- single sizing point
- PositionSizer is **mandatory** -- None means order rejection
- Capital from broker.fetch_available() (real-time)
- get_allocation_weights() called in orchestrator: after correlation gate, before PositionSizer
- PortfolioRiskManager is **mandatory** -- None means order rejection
- Unregistered strategies are **blocked** from entry
- TradingRuntime dataclass exposes PositionSizer, PortfolioRiskManager, PerformanceMonitor
- run_daemon() auto-started at bootstrap
- Graceful shutdown NOT needed -- daemon=True thread
- Monitor failure = log + continue (monitor down != trading down)
- check_interval_seconds configurable via bootstrap config
- All config values externally patchable -- no hardcoding

### Claude's Discretion
- OHLCV data delivery method (signal.metadata vs orchestrator re-fetch)
- PerformanceMonitor dependency assembly details (bootstrap internal vs external injection)
- Component activation control method (all mandatory vs config flag)
- BrokerPort get_balance() addition method

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RISK-01 | 실매매 전략의 20거래 롤링 윈도우 성과가 백테스트 기준 대비 저하되면 Discord 알림을 발송한다 | PerformanceMonitor already implements this (check_all -> _handle_warning/critical -> notifier.send_performance_alert). Wire run_daemon() in bootstrap with session_factory. |
| RISK-02 | ATR 또는 Kelly fraction 기반으로 변동성에 따른 가변 포지션 사이징이 적용된다 | PositionSizer.calculate() already implements ATR+Kelly. Wire into orchestrator.process_signal() replacing static quantity. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| (no new libraries) | -- | -- | Pure wiring of existing code |

This phase adds zero new dependencies. All components are already implemented.

## Architecture Patterns

### Pattern 1: Mandatory Injection with Guard
**What:** Constructor accepts component, process_signal() raises ValueError if None
**When to use:** PositionSizer and PortfolioRiskManager -- user decided these are mandatory
**Example:**
```python
# In TradingOrchestrator.__init__
def __init__(
    self,
    runtime_store: RuntimeStorePort,
    notifier: NotificationPort,
    broker: BrokerPort,
    position_sizer: PositionSizer,           # REQUIRED (no None default)
    portfolio_risk: PortfolioRiskManager,     # REQUIRED (no None default)
    event_notifier: EventNotifier | None = None,
    mtf_filter: MTFConfirmationGate | None = None,
) -> None:
```

**IMPORTANT:** Current callers (signal_scanner line 398, 452) pass `quantity=self.config.quantity`. After wiring, quantity is computed inside process_signal(), so the external `quantity` parameter must be removed or ignored.

### Pattern 2: Sizing Flow Inside process_signal()
**What:** After correlation gate passes, fetch allocation weight, then call PositionSizer.calculate()
**When to use:** Every full_auto order
**Flow:**
```
1. correlation gate (existing) -- PortfolioRiskManager.check_correlation_gate()
2. NEW: allocation_weight = portfolio_risk.get_allocation_weights().get(strategy_id, default)
3. NEW: capital = broker.fetch_available()
4. NEW: ohlcv = ... (discretion: from signal.metadata or re-fetch)
5. NEW: result = position_sizer.calculate(df, entry_price, side, capital, allocation_weight=weight)
6. NEW: quantity = result.quantity
7. MTF gate (existing)
8. _build_order(signal, quantity) (existing)
```

### Pattern 3: Bootstrap Dependency Assembly
**What:** build_trading_runtime() creates repos, lifecycle, session_factory and assembles PerformanceMonitor
**When to use:** Application startup
**Example:**
```python
# In build_trading_runtime()
from engine.core.database import get_session
from engine.core.repository import TradeRepository, BacktestRepository
from engine.strategy.lifecycle_manager import LifecycleManager
from engine.strategy.performance_monitor import StrategyPerformanceMonitor, PerformanceConfig

trade_repo = TradeRepository()
backtest_repo = BacktestRepository()
lifecycle = LifecycleManager()

monitor_config = PerformanceConfig(
    check_interval_seconds=runtime_config.monitor_interval,
)
monitor = StrategyPerformanceMonitor(
    trade_repo=trade_repo,
    backtest_repo=backtest_repo,
    lifecycle=lifecycle,
    runtime_store=store,
    notifier=notifier,
    config=monitor_config,
)
monitor.run_daemon(session_factory=get_session)
```

### Pattern 4: OHLCV Delivery via Signal Metadata
**What:** Scanner attaches OHLCV DataFrame to signal.metadata["ohlcv_df"] before calling process_signal()
**When to use:** Avoids redundant API call inside orchestrator
**Rationale:**
- signal_scanner already fetches OHLCV for signal generation (line 112: `provider.fetch_ohlcv`)
- Re-fetching inside orchestrator wastes API calls and adds latency
- signal.metadata is already dict[str, Any] at runtime (slots=True dataclass with dict field)
- Caveat: metadata type hint says `dict[str, str | int | float | bool]` but pd.DataFrame won't match -- use a separate attribute or pass via a side channel

**Alternative (simpler):** Orchestrator re-fetches OHLCV using broker/provider. Cleaner type safety but slower.

**Recommendation:** Attach OHLCV to signal.metadata at scanner level. The type hint is already violated in practice (signal.metadata contains nested dicts). Add `"ohlcv_df"` key.

### Pattern 5: Unregistered Strategy Blocking
**What:** If strategy_id not in portfolio_risk._active_signals, block entry
**When to use:** All entry signals in full_auto mode
**Implementation:** Check `strategy_id in portfolio_risk.get_allocation_weights()` or add a `is_registered(strategy_id)` method.

### Anti-Patterns to Avoid
- **Keeping quantity as external parameter:** process_signal(quantity=X) bypasses the sizer -- remove or deprecate
- **Optional PositionSizer:** User explicitly decided mandatory -- do not default to None
- **Monitor in orchestrator:** Monitor is decoupled (daemon thread) -- do not call check_all() from process_signal()
- **Hardcoded intervals/thresholds:** All config values must come from TradingRuntimeConfig or component-specific config dataclasses

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Position sizing | Custom math in orchestrator | PositionSizer.calculate() | Already handles ATR+Kelly+factor+allocation |
| Allocation weights | Manual weight calculation | PortfolioRiskManager.get_allocation_weights() | Already has Risk Parity |
| Performance monitoring | Custom check loop | StrategyPerformanceMonitor.run_daemon() | Already has daemon thread + per-strategy isolation |
| Balance query | Custom API call | BrokerPort.fetch_available() | Already in port interface + all brokers implement it |

## Common Pitfalls

### Pitfall 1: Breaking Existing Tests
**What goes wrong:** Changing process_signal() signature breaks 4 existing tests that pass quantity=X
**Why it happens:** Tests construct TradingOrchestrator without PositionSizer/PortfolioRiskManager
**How to avoid:** Update test fixtures to inject mock PositionSizer and PortfolioRiskManager. Tests that check quantity flow must mock position_sizer.calculate() to return a known PositionSizeResult.
**Warning signs:** test_orchestrator.py failures

### Pitfall 2: signal_scanner Caller Mismatch
**What goes wrong:** signal_scanner calls process_signal(signal, quantity=config.quantity) at lines 398 and 452
**Why it happens:** After wiring, quantity is computed internally -- the external parameter becomes dead code
**How to avoid:** Remove quantity parameter from process_signal() or mark it as deprecated. Update signal_scanner callers.
**Warning signs:** Quantity from config overriding sizer output

### Pitfall 3: OHLCV Not Available at Sizing Time
**What goes wrong:** PositionSizer.calculate() needs a DataFrame but process_signal() only receives TradingSignal
**Why it happens:** TradingSignal has no OHLCV field
**How to avoid:** Either (a) attach OHLCV to signal.metadata before calling process_signal(), or (b) re-fetch inside orchestrator using signal.symbol + signal.timeframe
**Warning signs:** KeyError on metadata["ohlcv_df"] or empty DataFrame passed to sizer

### Pitfall 4: Circular Import
**What goes wrong:** bootstrap.py importing from strategy/ and core/ modules that import back
**Why it happens:** PerformanceMonitor uses TYPE_CHECKING for repos but bootstrap does runtime imports
**How to avoid:** bootstrap.py does runtime imports at function scope (already the pattern for other components)
**Warning signs:** ImportError at startup

### Pitfall 5: Session Factory Lifecycle
**What goes wrong:** get_session() is a context manager, but run_daemon() needs a callable that returns a context manager
**Why it happens:** get_session is decorated with @contextmanager
**How to avoid:** Pass get_session directly -- run_daemon() already calls `with session_factory() as session:` which works with @contextmanager functions
**Warning signs:** TypeError on session_factory()

### Pitfall 6: Missing Strategy Registration
**What goes wrong:** get_allocation_weights() returns empty dict if no strategies are registered
**Why it happens:** Strategies must be registered via register_strategy() before allocation works
**How to avoid:** Ensure signal_scanner or bootstrap registers active strategies with PortfolioRiskManager. Or handle empty weights gracefully (default weight = 1.0 for unregistered strategies -- BUT user decided unregistered = blocked).

## Code Examples

### Current process_signal() Integration Points
```python
# Line 72-82: EXISTING correlation gate (keep as-is)
if self.portfolio_risk is not None:
    ...check_correlation_gate...

# NEW: Between correlation gate (line 82) and MTF gate (line 85)
# Insert: allocation weight fetch + position sizing

# Line 96: EXISTING _build_order (quantity comes from sizer now)
order = self._build_order(signal, quantity)
```

### Current signal_scanner Callers (must update)
```python
# Line 398: scan_once() for regular signals
self.orchestrator.process_signal(signal, quantity=self.config.quantity)

# Line 452: scan_once() for confluence signals
self.orchestrator.process_signal(signal, quantity=self.config.quantity)
```

### PositionSizer.calculate() Signature
```python
def calculate(
    self,
    df: pd.DataFrame,          # OHLCV
    entry_price: float,         # from signal.entry_price
    side: str,                  # from signal.side.value
    capital: float,             # from broker.fetch_available()
    config: ScalpRiskConfig | None = None,
    timeframe: str | None = None,  # from signal.timeframe
    trade_stats: dict | None = None,
    allocation_weight: float = 1.0,  # from portfolio_risk.get_allocation_weights()
) -> PositionSizeResult:
```

### TradingRuntimeConfig Extension
```python
@dataclass(slots=True)
class TradingRuntimeConfig:
    state_path: str | Path = "state/runtime_state.json"
    broker_plugin: str = "paper"
    notifier_plugin: str = "discord_webhook"
    runtime_store_plugin: str = "json"
    discord_config_path: str | Path = "config/discord.json"
    # NEW fields for Phase 9
    monitor_interval: int = 900           # PerformanceMonitor check interval
    monitor_warning_threshold: float = 0.15
    monitor_critical_sharpe: float = -0.5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static quantity from config | PositionSizer dynamic sizing | Phase 9 | Quantity based on ATR+Kelly+allocation |
| Optional portfolio risk | Mandatory portfolio risk | Phase 9 | Unregistered strategies blocked |
| No daemon monitor | PerformanceMonitor daemon | Phase 9 | Continuous performance evaluation |

## Open Questions

1. **OHLCV delivery mechanism**
   - What we know: Scanner already has OHLCV, PositionSizer needs it, orchestrator doesn't have it
   - What's unclear: Best way to pass DataFrame through signal boundary
   - Recommendation: Attach to signal.metadata["ohlcv_df"] at scanner level. Simple, avoids re-fetch. Type hint mismatch is acceptable (already violated in practice).

2. **trade_stats for Kelly**
   - What we know: PositionSizer needs trade_stats (win_rate, avg_win, avg_loss, n_trades) for Kelly
   - What's unclear: Where to fetch trade stats at sizing time
   - Recommendation: Query TradeRepository.summary() inside orchestrator or pass via signal.metadata. Orchestrator would need TradeRepository injection (or get it from PerformanceMonitor/bootstrap context).

3. **Strategy registration lifecycle**
   - What we know: PortfolioRiskManager requires register_strategy() before allocation works
   - What's unclear: When/where active strategies get registered
   - Recommendation: Bootstrap registers all "active" strategies from LifecycleManager at startup. Signal scanner could also register on first signal per strategy.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | (default pytest discovery) |
| Quick run command | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RISK-01 | PerformanceMonitor daemon starts at bootstrap and sends alerts on degradation | integration | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k monitor` | No -- Wave 0 |
| RISK-02 | process_signal() uses PositionSizer.calculate() for ATR/Kelly quantity | unit | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k sizer` | No -- Wave 0 |
| RISK-02 | allocation_weight applied from PortfolioRiskManager before sizing | unit | `.venv/bin/python -m pytest tests/trading/test_orchestrator.py -x -k allocation` | No -- Wave 0 |
| RISK-01+02 | bootstrap assembles all components and starts monitor daemon | integration | `.venv/bin/python -m pytest tests/trading/test_bootstrap.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/trading/ -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/trading/test_orchestrator.py` -- update existing 4 tests for mandatory PositionSizer/PortfolioRiskManager injection
- [ ] `tests/trading/test_orchestrator.py` -- add tests for sizer wiring, allocation weight, strategy blocking
- [ ] `tests/trading/test_bootstrap.py` -- new file for bootstrap assembly + monitor daemon start

## Sources

### Primary (HIGH confidence)
- Direct code reading: orchestrator.py, bootstrap.py, position_sizer.py, portfolio_risk.py, performance_monitor.py, signal_scanner.py, ports.py, database.py, models.py, risk_manager.py, plugin_runtime.py, repository.py
- Existing test: tests/trading/test_orchestrator.py

### Secondary (MEDIUM confidence)
- None needed -- pure internal wiring, no external libraries

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, pure wiring
- Architecture: HIGH -- all patterns already established in codebase (constructor injection, plugin registry, try/except guards)
- Pitfalls: HIGH -- identified from direct code reading of all integration points

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable -- internal wiring only)

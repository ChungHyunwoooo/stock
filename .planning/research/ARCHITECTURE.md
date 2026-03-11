# Architecture Research

**Domain:** Automated trading pipeline — strategy lifecycle automation
**Researched:** 2026-03-11
**Confidence:** HIGH (based on direct codebase analysis + established industry patterns)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        interfaces/                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ Discord Bot  │  │   FastAPI    │  │  Streamlit   │  │    CLI     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
├─────────┴─────────────────┴─────────────────┴────────────────┴──────────┤
│                        application/ (NEW SERVICES HERE)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  Orchestrator│  │LifecycleMgr  │  │PortfolioRisk │  │PerfMonitor │  │
│  │  (existing)  │  │  (NEW)       │  │  (NEW)       │  │  (NEW)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
├─────────┴─────────────────┴─────────────────┴────────────────┴──────────┤
│  strategy/ (detection, risk)  │  backtest/ (runner, optimizer)           │
│  ┌──────────────┐  ┌──────────┴────────────────────────────────────┐    │
│  │  RiskManager │  │  AutoDiscoveryEngine (NEW)  BacktestRunner     │    │
│  │  (existing)  │  │  IndicatorSweeper (NEW)     GridOptimizer      │    │
│  └──────┬───────┘  └──────────┬────────────────────────────────────┘    │
├─────────┴─────────────────────┴──────────────────────────────────────────┤
│  execution/ (brokers)   notifications/   indicators/   data/             │
│  ┌──────────┐ ┌───────┐  ┌────────────┐  ┌──────────┐  ┌────────────┐  │
│  │PaperBroker│ │Binance│  │DiscordHook │  │ REGISTRY │  │ProviderBase│  │
│  └──────────┘ └───────┘  └────────────┘  └──────────┘  └────────────┘  │
├──────────────────────────────────────────────────────────────────────────┤
│  core/ — models, ports (Protocol), db, repository                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Layer | Status |
|-----------|---------------|-------|--------|
| `core/ports.py` | BrokerPort, NotificationPort, RuntimeStorePort Protocol interfaces | core | existing |
| `schema.py:StrategyDefinition` | System-wide strategy contract (Pydantic) | core | existing |
| `schema.py:StrategyStatus` | draft → testing → active → archived state machine | core | existing — extend with `paper` |
| `backtest/runner.py:BacktestRunner` | Single strategy replay over OHLCV, returns BacktestResult | backtest | existing |
| `backtest/optimizer.py:GridOptimizer` | Exhaustive grid search over param combinations | backtest | existing |
| `backtest/parallel_optimizer.py` | Parallel version of GridOptimizer | backtest | existing |
| `strategy/plugin_registry.py:PluginRegistry` | Generic factory registry (broker/notifier/store) | strategy | existing |
| `execution/paper_broker.py:PaperBroker` | In-memory simulated order execution | execution | existing — extend for paper-live bridge |
| `application/trading/orchestrator.py:TradingOrchestrator` | signal → alert/semi_auto/auto routing | application | existing |
| `strategy/risk_manager.py:RiskManager` | Per-symbol position limits, daily loss, consecutive SL | strategy | existing — portfolio level missing |
| **`backtest/auto_discovery.py`** | Indicator combination sweep, generate candidate StrategyDefinitions | backtest | **NEW** |
| **`application/trading/lifecycle_manager.py`** | draft → backtest → paper → active → archived state transitions | application | **NEW** |
| **`application/portfolio/risk_manager.py`** | Cross-strategy correlation, total exposure, capital allocation | application | **NEW** |
| **`application/portfolio/performance_monitor.py`** | Real-time strategy performance tracking, degradation detection | application | **NEW** |
| **`interfaces/streamlit_dashboard.py`** | Live positions, strategy status, perf charts, discovery queue | interfaces | extend existing stub |

## Recommended Project Structure

```
engine/
├── backtest/
│   ├── runner.py              # existing — unchanged
│   ├── optimizer.py           # existing — unchanged
│   ├── parallel_optimizer.py  # existing — unchanged
│   ├── metrics.py             # existing — unchanged
│   ├── auto_discovery.py      # NEW: indicator sweep + candidate generation
│   └── slippage_model.py      # NEW: data-driven slippage/fee modeling
│
├── application/
│   ├── trading/               # existing service layer
│   │   ├── orchestrator.py    # existing — unchanged
│   │   ├── lifecycle_manager.py  # NEW: strategy lifecycle state machine
│   │   └── strategy_monitor.py   # existing — extend with perf tracking
│   └── portfolio/             # NEW: portfolio-level concerns
│       ├── __init__.py
│       ├── risk_manager.py    # NEW: cross-strategy risk
│       └── performance_monitor.py  # NEW: degradation detection
│
├── execution/
│   ├── paper_broker.py        # existing — extend with live position tracking
│   └── paper_live_bridge.py   # NEW: graduation logic paper→live
│
├── interfaces/
│   ├── streamlit_dashboard.py # extend existing stub
│   └── discord/               # existing — extend with lifecycle commands
│
└── core/
    ├── ports.py               # extend with PortfolioPort, LifecyclePort
    └── models.py              # extend with StrategyPerformanceRecord
```

### Structure Rationale

- **`backtest/auto_discovery.py`:** Belongs in `backtest/` not `strategy/` — it produces `StrategyDefinition` candidates via mass replay; it does not run live. Keeps backtest/ self-contained.
- **`application/portfolio/`:** New sub-package. Portfolio concerns (cross-strategy correlation, capital allocation) are orthogonal to single-strategy orchestration. Separate package prevents `trading/orchestrator.py` from growing into a god object.
- **`execution/paper_live_bridge.py`:** Thin bridge logic that checks paper performance thresholds and triggers graduation. Belongs in `execution/` because it wraps broker state transition, not strategy logic.
- **`core/ports.py` extension:** New `PortfolioPort` and `LifecyclePort` Protocols keep application layer decoupled from concrete implementations.

## Architectural Patterns

### Pattern 1: Extend Existing StrategyStatus State Machine

**What:** Add `paper` status between `testing` and `active` in `schema.py:StrategyStatus`. The lifecycle manager transitions strategies through: `draft → testing → paper → active → archived`.

**When to use:** Every strategy promotion/demotion goes through this state machine — never jump states directly.

**Trade-offs:** Single source of truth for strategy stage. Requires `registry.json` and `definition.json` to stay in sync — lifecycle manager owns both writes.

```python
# engine/schema.py — extend enum
class StrategyStatus(str, Enum):
    draft = "draft"
    testing = "testing"    # backtest validation phase
    paper = "paper"        # NEW: paper trading validation phase
    active = "active"      # live trading
    archived = "archived"  # retired

# engine/application/trading/lifecycle_manager.py
class StrategyLifecycleManager:
    def promote(self, strategy_id: str) -> StrategyStatus: ...
    def demote(self, strategy_id: str, reason: str) -> StrategyStatus: ...
    def archive(self, strategy_id: str, reason: str) -> None: ...
```

### Pattern 2: Auto-Discovery as BacktestRunner Consumer

**What:** `auto_discovery.py` generates `StrategyDefinition` candidates by sweeping indicator combinations, then feeds each candidate into the existing `BacktestRunner.run()`. No new evaluation engine — reuse exactly what exists.

**When to use:** Strategy discovery phase. Runs offline (CLI or scheduled job), not in the live trading thread.

**Trade-offs:** CPU-intensive. Use `parallel_optimizer.py` pattern (multiprocessing pool) to avoid blocking the API process. Results stored in SQLite via existing `repository.py`.

```python
# engine/backtest/auto_discovery.py
class IndicatorSweeper:
    """Generate StrategyDefinition candidates from indicator combination grid."""

    def __init__(self, runner: BacktestRunner) -> None:
        self._runner = runner

    def sweep(
        self,
        indicator_pool: list[str],          # e.g. ["RSI", "MACD", "BBANDS"]
        symbols: list[str],
        periods: list[tuple[str, str]],     # (start, end) multi-period stability check
        min_sharpe: float = 0.5,
        min_trades: int = 20,
    ) -> list[tuple[StrategyDefinition, BacktestResult]]: ...
```

### Pattern 3: Portfolio Risk as a Gate in TradingOrchestrator

**What:** Before `TradingOrchestrator.process_signal()` executes an order, call `PortfolioRiskManager.allow_entry(signal)`. Portfolio risk gates on total capital exposure, cross-strategy correlation, and per-regime concentration.

**When to use:** Every live trade entry — `semi_auto` and `auto` modes only. `alert_only` mode bypasses the gate (just notifying, not executing).

**Trade-offs:** Centralizes portfolio constraints in one place. The portfolio risk manager needs read access to all open positions across strategies — use the existing `BrokerPort.fetch_open_positions()` to avoid a new data source.

```python
# engine/core/ports.py — add new port
class PortfolioRiskPort(Protocol):
    def allow_entry(self, signal: TradingSignal, open_positions: list[dict]) -> bool: ...
    def capital_allocation(self, strategy_id: str) -> float: ...
    def get_portfolio_status(self) -> dict: ...

# TradingOrchestrator.process_signal() gains one pre-execution gate:
# if not self.portfolio_risk.allow_entry(signal, self.broker.fetch_open_positions()):
#     self.notifier.send_text(f"Portfolio gate blocked: {signal.symbol}")
#     return state
```

### Pattern 4: Performance Monitor as a Read-Only Observer

**What:** `PerformanceMonitor` reads `ExecutionRecord` rows from the existing SQLite repository and computes rolling metrics per strategy. It does NOT write to the orchestrator — it only emits alerts via `NotificationPort` when degradation is detected. Control stays with the human.

**When to use:** Runs as a scheduled background task (extend `engine/strategy/scheduler.py`), not in the hot path.

**Trade-offs:** Decoupled from execution path — a monitor crash cannot affect live trading. Degradation threshold configuration lives in `config/performance_monitor.json` via `engine/config_path.py`.

```python
# engine/application/portfolio/performance_monitor.py
class StrategyPerformanceMonitor:
    def __init__(self, repo: TradeRepository, notifier: NotificationPort) -> None: ...

    def check_all_active_strategies(self) -> list[DegradationAlert]:
        """Read-only scan. Emits alerts but never mutates state."""
        ...

    def _detect_degradation(
        self,
        strategy_id: str,
        recent_window: int = 20   # last N trades
    ) -> DegradationAlert | None: ...
```

### Pattern 5: Paper-Live Bridge via Broker Plugin Swap

**What:** A strategy in `paper` status runs through `PaperBroker`. When graduation criteria are met (N days, min Sharpe, max drawdown), `paper_live_bridge.py` updates `registry.json` status to `active` and swaps the broker plugin for that strategy to the live broker. The swap happens via `plugin_runtime.py` — existing infrastructure handles the rest.

**When to use:** Promotion from `paper → active` only. Demotion (`active → paper`) follows the same path in reverse.

**Trade-offs:** Each strategy effectively has its own broker instance (or a shared live broker that validates per-strategy). The existing `PluginRegistry` pattern supports this — register a per-strategy broker keyed by `strategy_id` rather than exchange name.

## Data Flow

### Strategy Discovery Flow

```
CLI / Scheduled Job
    ↓
IndicatorSweeper.sweep(indicator_pool, symbols, periods)
    ↓ (per candidate StrategyDefinition)
BacktestRunner.run() × N  [parallel via ProcessPoolExecutor]
    ↓
Filter: sharpe >= threshold AND trades >= min AND stable across periods
    ↓
Save candidate to: strategies/{id}/definition.json  (status="draft")
Update: strategies/registry.json
    ↓
NotificationPort.send_text("New candidate: {id}, Sharpe={x}")
```

### Strategy Lifecycle Promotion Flow

```
LifecycleManager.promote(strategy_id)
    ↓
Current status? draft → testing:
    Run BacktestRunner over validation period (multi-symbol, multi-period)
    Pass threshold? → set status="testing", save definition.json
    ↓
testing → paper:
    Enable PaperBroker for this strategy_id in plugin_runtime.py
    Set status="paper", save definition.json
    ↓
paper → active (after N days + meets criteria):
    Swap broker plugin: paper → live broker
    Set status="active", save definition.json
    Notify Discord: "Strategy {id} promoted to live"
    ↓
active → archived (manual or degradation trigger):
    Cancel open positions via BrokerPort
    Set status="archived", record reason in registry.json
```

### Portfolio Risk Gate Flow

```
TradingOrchestrator.process_signal(signal)
    ↓
Load TradingRuntimeState (existing)
    ↓ [NEW GATE]
PortfolioRiskManager.allow_entry(signal, broker.fetch_open_positions())
    ↓ blocked?
        NotificationPort.send_text("Blocked: {reason}")
        return state  (no order)
    ↓ allowed?
Continue existing flow: alert_only / semi_auto / auto
```

### Performance Monitoring Flow

```
Scheduler (engine/strategy/scheduler.py) every 15min
    ↓
PerformanceMonitor.check_all_active_strategies()
    ↓ (per strategy_id with status="active")
TradeRepository.list_recent(strategy_id, limit=20)  [existing repo]
    ↓
Compute: rolling_sharpe, rolling_win_rate, max_drawdown_recent
    ↓ degradation detected?
NotificationPort.send_text("ALERT: {strategy_id} degraded — {metrics}")
    (human reviews + manually archives if needed)
```

### Dashboard Data Flow

```
Streamlit Dashboard (polling / websocket)
    ↓ reads
BrokerPort.fetch_open_positions()       → live positions panel
TradeRepository.list_recent()           → recent trades panel
PerformanceMonitor.get_strategy_stats() → performance charts
LifecycleManager.get_pipeline_status()  → strategy queue panel
IndicatorSweeper.get_discovery_queue()  → discovery progress panel
```

## Component Boundaries (What Talks to What)

| Component | Reads From | Writes To | Must NOT Touch |
|-----------|-----------|----------|----------------|
| `auto_discovery.py` | `DataProvider`, `IndicatorRegistry` | `strategies/*/definition.json`, `registry.json` | live broker, orchestrator |
| `lifecycle_manager.py` | `registry.json`, `BacktestRunner` | `definition.json`, `registry.json`, `plugin_runtime` | trade execution directly |
| `portfolio/risk_manager.py` | `BrokerPort.fetch_open_positions()` | nothing (stateless gate) | `registry.json`, broker orders |
| `performance_monitor.py` | `TradeRepository` | `NotificationPort` only | orchestrator, broker, lifecycle |
| `paper_live_bridge.py` | `PaperBroker` state, performance metrics | `plugin_runtime` (broker swap), `lifecycle_manager` | OHLCV data, indicators |
| `TradingOrchestrator` | `PortfolioRiskPort` (NEW gate) | `RuntimeStorePort`, `NotificationPort`, `BrokerPort` | backtest layer, discovery |

## Suggested Build Order (Phase Dependencies)

### Phase 1: Foundation — Extend Schema + Lifecycle Manager
**Dependency:** Everything downstream depends on `paper` status existing.
- Add `paper` to `StrategyStatus` enum
- Implement `LifecycleManager` (state machine only, no broker swap yet)
- Extend `registry.json` schema with `deprecated_reason`, `paper_start_date`

### Phase 2: Advanced Backtester + Slippage Model
**Dependency:** Auto-discovery (Phase 3) needs the enhanced backtest quality gate.
- Add data-driven slippage model to `BacktestRunner`
- Multi-period stability check (walk-forward validation)
- Multi-market parallel runs
- Pluggable scoring function (not just Sharpe — add win-rate floor, trade count floor)

### Phase 3: Auto-Discovery Engine
**Dependency:** Phase 2 backtester, Phase 1 schema.
- `IndicatorSweeper` in `backtest/auto_discovery.py`
- Uses `parallel_optimizer.py` pattern (existing)
- Saves candidates as `draft` status
- Discord notification on new candidates

### Phase 4: Paper Trading Bridge
**Dependency:** Phase 1 lifecycle, existing `PaperBroker`.
- Extend `PaperBroker` to track realistic fill simulation (existing orders table)
- `paper_live_bridge.py` graduation criteria checker
- Wire lifecycle `testing → paper` transition to broker plugin swap

### Phase 5: Portfolio Risk Manager
**Dependency:** Phase 4 paper bridge (need multi-strategy position data).
- `PortfolioRiskManager` implementing new `PortfolioRiskPort`
- Register as a gate in `TradingOrchestrator.process_signal()`
- Capital allocation logic (Kelly-based or fixed-fractional)
- Cross-strategy correlation check (uses historical returns from `TradeRepository`)

### Phase 6: Performance Monitor
**Dependency:** Phase 4 (paper + live positions generating trade records).
- `PerformanceMonitor` as a scheduler task
- Rolling metric computation from `TradeRepository`
- Degradation thresholds in `config/performance_monitor.json`

### Phase 7: Monitoring Dashboard
**Dependency:** All prior phases (data sources must exist).
- Extend `interfaces/streamlit_dashboard.py`
- Portfolio view, lifecycle pipeline view, discovery queue
- Discord bot commands for lifecycle control (`/전략승격`, `/전략퇴출`)

## Anti-Patterns

### Anti-Pattern 1: New Evaluation Engine in `strategy/`

**What people do:** Build a separate strategy evaluator for auto-discovery that duplicates `condition_evaluator.py` + `StrategyEngine`.
**Why it's wrong:** Creates two code paths that diverge — a strategy that passes auto-discovery may not behave the same in live trading.
**Do this instead:** Auto-discovery feeds generated `StrategyDefinition` objects into the existing `BacktestRunner.run()` which uses the existing `StrategyEngine`. One evaluation path.

### Anti-Pattern 2: Portfolio Risk in `strategy/risk_manager.py`

**What people do:** Add portfolio-level logic (cross-strategy correlation, total capital) to the existing per-strategy `RiskManager`.
**Why it's wrong:** `RiskManager` is instantiated per-strategy with `SymbolState` per symbol. Adding portfolio-level state means it needs to know about other strategies — wrong layer.
**Do this instead:** New `application/portfolio/risk_manager.py`. Reads aggregate data from `BrokerPort.fetch_open_positions()` which has the full picture.

### Anti-Pattern 3: Auto-Promotion Without Human Confirmation

**What people do:** Automatically promote a strategy from `paper → active` when thresholds are met, without a Discord confirmation step.
**Why it's wrong:** Paper trading metrics can look good on a short window due to favorable market conditions. The stated design principle is "성과 저하 시 알림만, 교체는 수동 판단."
**Do this instead:** `LifecycleManager` sends a Discord alert with promotion criteria met, but sets status to `paper_ready` (or equivalent flag). Promotion to `active` requires `/전략승격 {id}` Discord command from operator.

### Anti-Pattern 4: Blocking Discovery in API Process

**What people do:** Trigger `IndicatorSweeper.sweep()` as a FastAPI route handler — blocking the event loop for minutes.
**Why it's wrong:** Discovery involves hundreds of `BacktestRunner.run()` calls over historical data. Blocks all API requests.
**Do this instead:** Run discovery as a background task via `scheduler.py` (existing cron scheduler) or as a CLI command (`engine/cli.py`). FastAPI route only submits a job and returns a task ID.

### Anti-Pattern 5: Separate SQLite DB for Portfolio State

**What people do:** Create a new `portfolio.db` for portfolio risk state and performance metrics.
**Why it's wrong:** `tse.db` already has `TradeRepository` and the SQLAlchemy setup. Fragmentation means joins between strategy trades and portfolio state require cross-DB queries.
**Do this instead:** Extend `engine/core/db_models.py` with `StrategyPerformanceRecord` and `PortfolioSnapshot` tables in the existing `tse.db`.

## Integration Points

### Internal Boundaries

| Boundary | Communication Pattern | Notes |
|----------|-----------------------|-------|
| `auto_discovery` → `backtest/runner` | Direct call — `BacktestRunner.run()` | Run in ProcessPoolExecutor pool to avoid GIL |
| `lifecycle_manager` → `plugin_runtime` | Direct call — `broker_plugins.create()` swap | Needs `strategy_id` keying added to plugin registry |
| `portfolio/risk_manager` → `TradingOrchestrator` | Protocol gate — `PortfolioRiskPort.allow_entry()` | Injected at bootstrap in `interfaces/bootstrap.py` |
| `performance_monitor` → `TradeRepository` | Direct repo call — read-only | No lock needed; SQLite read-only from monitor thread |
| `performance_monitor` → `NotificationPort` | Protocol call | Existing `DiscordWebhookNotifier` — no new infrastructure |
| `lifecycle_manager` → `NotificationPort` | Protocol call | Same notifier instance wired at bootstrap |

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Binance/Upbit | `BrokerPort` (existing) — unchanged | Paper bridge only swaps which broker instance is active |
| Discord | `NotificationPort` (existing) — extend message types | Add lifecycle event message formatters in `notifications/` |
| SQLite `tse.db` | `TradeRepository` + new `StrategyPerformanceRecord` table | Extend `db_models.py`, not a new DB file |

## Sources

- Direct codebase analysis: `engine/core/ports.py`, `engine/schema.py`, `engine/backtest/runner.py`, `engine/backtest/optimizer.py`, `engine/application/trading/orchestrator.py`, `engine/strategy/risk_manager.py`, `engine/strategy/plugin_runtime.py`, `strategies/registry.json`
- Existing lifecycle evidence: `StrategyStatus` enum (draft/testing/active/archived) in `schema.py`; `strategies/registry.json` shows `deprecated_reason` + `deprecated_date` fields already in use
- Existing paper trading evidence: `PaperBroker` registered as `"paper"` in `plugin_runtime.py`; `broker_factory.py` returns `PaperBroker` as default
- Existing parallel pattern: `engine/backtest/parallel_optimizer.py` — ProcessPoolExecutor pattern to follow for auto-discovery

---
*Architecture research for: automated trading pipeline — strategy lifecycle automation*
*Researched: 2026-03-11*

# Project Research Summary

**Project:** AutoTrader — Automated Trading Pipeline
**Domain:** Crypto/stock automated trading — strategy discovery, backtesting, paper trading, live execution
**Researched:** 2026-03-11
**Confidence:** HIGH (architecture from direct codebase analysis; stack from PyPI verification; pitfalls from industry consensus)

## Executive Summary

This project extends an existing, well-structured automated trading engine (Python 3.12, ccxt, TA-Lib, FastAPI, Discord.py, SQLite) into a complete strategy lifecycle pipeline: from automated discovery through backtest validation to paper trading and live deployment. The existing codebase has strong foundations — per-strategy risk management, a broker abstraction layer, a scanner daemon, and 17+ strategy definitions — but is missing the quality gates that make automated trading safe to run with real capital: walk-forward validation, realistic cost modeling, enforced paper trading stage, and portfolio-level risk controls.

The recommended approach is additive and layered. No existing modules need to be replaced. Five new libraries cover the gaps (optuna for parameter search, vectorbt for sweep-speed backtesting, riskfolio-lib for portfolio optimization, APScheduler for pipeline orchestration, Streamlit/Plotly upgrade for dashboard). The architecture is already layered correctly — new components slot into `application/portfolio/` (cross-strategy concerns) and `backtest/auto_discovery.py` (discovery engine) without touching the existing execution or strategy layers. All new state belongs in the existing `tse.db` SQLite database, not in a new file.

The critical risk in this domain is deploying curve-fitted strategies. Every pitfall identified — single-period overfitting, lookahead bias, zero slippage modeling, no holdout data, correlation blindness — stems from skipping validation steps that feel redundant but are not. The build order must enforce: cost model → walk-forward → paper stage → portfolio risk → live promotion. Reversing this order will produce strategies that look profitable in backtest and lose money in production. The design principle "alert, human decides promotion" must be enforced in code, not policy.

## Key Findings

### Recommended Stack

The existing stack covers data ingestion, indicators, patterns, execution, and notification. Five additive libraries are needed. No existing library needs to be replaced.

**Core additive technologies:**
- `optuna 4.7.0`: Bayesian hyperparameter search (TPE + CMA-ES) for indicator/param sweeps — industry-standard choice used by freqtrade in production; define-by-run API fits existing backtest loop
- `vectorbt 0.28.4`: NumPy/Numba-accelerated backtesting for multi-parameter sweep speed — complementary to existing `bt` (keep `bt` for single-strategy reporting, use `vectorbt` for bulk sweep validation)
- `riskfolio-lib 7.0+`: Portfolio optimization with HRP (Hierarchical Risk Parity) and Kelly-criterion sizing — directly addresses cross-strategy correlation and capital allocation requirements
- `APScheduler 3.10+`: BackgroundScheduler for pipeline orchestration (discovery jobs, performance checks) — uses existing SQLAlchemy jobstore in `tse.db`, no new infrastructure
- `streamlit 1.55.0` + `plotly 5.x`: Upgrade existing dashboard stub — `st.rerun()` pattern for live updates
- `ccxt.pro` WebSocket: Already bundled in ccxt 4.2+, architecture change only — requires `asyncio` + `watch*` methods for real-time data in paper trading

**Libraries to avoid:** `pyfolio` (broken on pandas 2.x), `backtrader` (development stopped 2018, Python 3.12 incompatible), `zipline` (Python 3.5-3.6 era), `ray[tune]` (distributed cluster overkill for single machine), `celery` (requires Redis/RabbitMQ broker).

### Expected Features

**Must have (table stakes — pipeline is not safe to run live without these):**
- Realistic slippage + fee model — without this, no backtest result is credible for live deployment decisions
- Walk-forward validation (multi-period OOS test) — single-period Sharpe sorting guarantees curve-fitting
- Multi-market stability check — strategy must hold across 2-3 uncorrelated symbols, not just one
- Persistent paper trading stage with PnL tracking — PaperBroker exists, needs session-persistent state
- Paper → live promotion gate (quantitative criteria) — must be code, not manual checklist
- Portfolio-level daily loss limit — per-strategy limits exist; gap is when 5 strategies lose simultaneously
- Strategy lifecycle state machine with enforced transitions — `StrategyStatus` enum exists, transitions are currently manual
- Performance degradation alert — rolling 20-trade window metrics vs. backtest baseline

**Should have (competitive differentiators, add after v1 validation):**
- Backtest report persistence + comparison — extend existing DB, low complexity, high value
- Adaptive position sizing (ATR-based or Kelly-fraction) — replaces fixed 2% risk_per_trade_pct
- Multi-timeframe confirmation gate — `mtf_confluence.py` exists, needs wiring as entry gate
- Reference-strategy importer workflow — structured process for adding curated strategies to registry
- Monitoring dashboard (Streamlit extension) — existing stub in `interfaces/streamlit_dashboard.py`

**Defer to v2+:**
- Automated indicator-combination sweep — high complexity, requires walk-forward + stability check in place first
- Strategy correlation filter — needs signal history schema and 5+ concurrent live strategies to be meaningful
- CPCV walk-forward (Combinatorial Purged Cross-Validation) — upgrade from basic OOS split; basic walk-forward first
- ccxt multi-exchange expansion — defer until single-exchange pipeline is stable

**Anti-features to explicitly reject:**
- Automatic strategy replacement on degradation (73% of fully-automated bots fail within 6 months)
- HFT/sub-second execution (requires co-location + C++ execution layer, incompatible with Python stack)
- Real-time polling every second in dashboard (100 DB queries/second under any real load)

### Architecture Approach

The existing 3-layer architecture (`core/` → domain layer, `application/` → service layer, `interfaces/` → user-facing) is correct and must be preserved. New components slot into well-defined gaps without modifying existing modules. The central pattern is: extend the existing `StrategyStatus` enum with a `paper` state, add two new application sub-packages (`application/portfolio/` for cross-strategy concerns, `application/trading/lifecycle_manager.py` for state machine enforcement), and add one new backtest module (`backtest/auto_discovery.py` + `backtest/slippage_model.py`).

**Major new components:**
1. `backtest/slippage_model.py` — `SlippageModel` interface with `ZeroSlippage`, `FixedBpsSlippage`, `VolumeAdjustedSlippage` implementations; plugged into `BacktestRunner`
2. `backtest/auto_discovery.py` — `IndicatorSweeper` that generates `StrategyDefinition` candidates by sweeping indicator combinations through existing `BacktestRunner.run()`; runs offline only
3. `application/trading/lifecycle_manager.py` — `StrategyLifecycleManager` enforcing `draft → testing → paper → active → archived` transitions; owns writes to `registry.json` and `definition.json`
4. `application/portfolio/risk_manager.py` — `PortfolioRiskManager` implementing new `PortfolioRiskPort`; stateless gate called by `TradingOrchestrator.process_signal()` before every live entry
5. `application/portfolio/performance_monitor.py` — `StrategyPerformanceMonitor` as read-only scheduler task; reads `TradeRepository`, emits Discord alerts, never touches orchestrator or broker
6. `execution/paper_live_bridge.py` — graduation criteria checker; swaps broker plugin from `PaperBroker` to live broker via existing `plugin_runtime.py` when criteria are met

**Enforced boundaries:** `auto_discovery` never touches live broker or orchestrator. `performance_monitor` never writes to orchestrator or broker — alert only, human decides. `portfolio/risk_manager` is stateless — reads positions, returns bool, writes nothing. `lifecycle_manager` never executes trades directly.

### Critical Pitfalls

1. **Single-period curve fitting** — Walk-forward validation must be a mandatory gate before any strategy advances from `testing` to `paper`. Current optimizer sorts by in-sample Sharpe only; this selects curve-fitted strategies with near certainty. Warning sign: optimizer top result Sharpe > 3.0.

2. **Lookahead bias (close as fill price)** — Current `BacktestRunner._simulate()` fills entries at signal-bar close. Realistic fill is next-bar open. For 1m scalping this gap compounds to significant underperformance. Fix before running any sweep results are trusted.

3. **Zero slippage / zero fees** — Current backtest applies no cost model. A strategy with 100 round-trips/month at 0.1% total cost burns 10%/month in costs alone. Build `VolumeAdjustedSlippage` and apply it as default before optimizer results are used for strategy selection.

4. **No holdout data reservation** — First true OOS test becomes live trading with real money. Reserve most recent 20-30% of historical data as permanently sealed holdout. Automate enforcement in the data pipeline — optimizer must be blocked from accessing holdout-period data.

5. **Strategy correlation ignored in portfolio construction** — Two strategies that appear uncorrelated in trending markets show near-perfect correlation during flash crashes. Compute rolling 30-day P&L correlation matrix before any multi-strategy live deployment; reject any pair with correlation > 0.7 in stress regimes.

6. **Paper trading duration too short** — 1-2 weeks paper trading is insufficient to observe regime changes. Minimum: 4 weeks for 1m/5m strategies (must include one high-volatility event), 6 weeks for 15m/1h, 3 months for 4h/1d.

7. **Strategy degradation detected only after major loss** — Without rolling metric monitoring, gradual edge decay accumulates undetected for weeks. Implement rolling 20-trade window Sharpe and win-rate monitoring before any strategy goes live.

## Implications for Roadmap

Based on combined research, the dependency chain mandates a specific phase order. The cost model must precede walk-forward (OOS results are meaningless without costs). Walk-forward must precede automated sweep (sweep is only safe after OOS validation exists). Paper stage must precede portfolio risk (need multi-strategy position data). Performance monitoring must be live before any strategy reaches production.

### Phase 1: Schema + Lifecycle Foundation

**Rationale:** Everything downstream depends on `paper` state existing in the enum and `LifecycleManager` enforcing transitions. This is zero-risk (schema extension only) and unlocks all later phases.
**Delivers:** Extended `StrategyStatus` enum (`paper` added), `LifecycleManager` with enforced state transitions, extended `registry.json` schema, Discord commands for lifecycle control (`/전략승격`, `/전략퇴출`).
**Addresses:** Strategy lifecycle state machine (P1 table stakes)
**Avoids:** Draft strategies entering live execution accidentally

### Phase 2: Backtest Quality Gates

**Rationale:** No optimizer result can be trusted until lookahead bias is fixed and cost model is in place. This phase must complete before Phase 3 sweep uses optimizer results for strategy selection.
**Delivers:** `BacktestRunner` with next-bar-open fill price model, `SlippageModel` interface with `VolumeAdjustedSlippage`, walk-forward OOS validation (multi-window), multi-market stability check (parallel runs on symbol basket), backtest report persistence in `tse.db`.
**Uses:** `vectorbt 0.28.4` for sweep-speed validation; `joblib` for parallel multi-symbol runs
**Implements:** `backtest/slippage_model.py`
**Avoids:** Pitfalls 1 (curve fitting), 2 (lookahead bias), 3 (zero slippage), 4 (no holdout)

### Phase 3: Paper Trading Stage

**Rationale:** Walk-forward (Phase 2) validates strategy candidates. Paper trading provides live-market validation before capital is at risk. Requires Phase 1 lifecycle state machine to enforce paper/active separation.
**Delivers:** Persistent `PaperBroker` state (session-persistent PnL tracking), `paper_live_bridge.py` graduation criteria checker (Sharpe, trade count, duration, drawdown gates), automated promotion alert (Discord) requiring human `/전략승격` command to finalize.
**Addresses:** Paper trading stage (P1), Paper → live promotion gate (P1)
**Avoids:** Pitfall 6 (paper trading too short); Anti-pattern 3 (auto-promotion without human confirmation)

### Phase 4: Portfolio Risk Manager

**Rationale:** Once multiple strategies can exist in paper and active states simultaneously, cross-strategy risk exposure becomes real. Portfolio risk gate must be in place before 2+ strategies are active concurrently.
**Delivers:** `PortfolioRiskManager` as stateless gate in `TradingOrchestrator.process_signal()`, portfolio-level daily loss limit (aggregate across all open strategies), cross-strategy correlation check using `riskfolio-lib`, `PortfolioRiskPort` protocol in `core/ports.py`.
**Uses:** `riskfolio-lib 7.0+` for HRP and Kelly-fraction capital allocation; `scikit-learn` for correlation clustering
**Implements:** `application/portfolio/risk_manager.py`
**Avoids:** Pitfall 5 (correlated strategies all stop simultaneously)

### Phase 5: Performance Degradation Monitoring

**Rationale:** With live strategies executing, degradation detection must be operational before losses can compound undetected. Runs as a scheduler task — read-only, decoupled from execution path.
**Delivers:** `StrategyPerformanceMonitor` running on 15-minute schedule, rolling 20-trade window metrics (Sharpe, win rate, profit factor), Discord alert thresholds (WARNING at 15% win-rate drop, CRITICAL at Sharpe < 0 over 20-trade window, AUTO-PAUSE at rolling 30-trade Sharpe < -0.5), configuration in `config/performance_monitor.json`.
**Uses:** `APScheduler 3.10+` for scheduler integration
**Implements:** `application/portfolio/performance_monitor.py`
**Addresses:** Performance degradation alert (P1)
**Avoids:** Pitfall 7 (degradation undetected until major loss)

### Phase 6: Auto-Discovery Engine

**Rationale:** Only safe after Phases 2-5 are complete — sweep produces draft candidates that must pass walk-forward, paper validation, and portfolio risk before live deployment. Building sweep before quality gates exist produces overfit candidates that waste paper trading cycles.
**Delivers:** `IndicatorSweeper` in `backtest/auto_discovery.py`, constrained sweep over existing indicator registry (2-3 indicator combinations, pre-defined param ranges), multiple-comparisons correction (Sharpe > 1.0 floor + parameter robustness check + cross-market validation), candidate saved as `draft` status with Discord notification.
**Uses:** `optuna 4.7.0` for Bayesian parameter search; `joblib` for parallel backtest workers
**Implements:** `backtest/auto_discovery.py`
**Avoids:** Pitfall 8 (multiple comparisons / spurious discoveries)

### Phase 7: Monitoring Dashboard

**Rationale:** All data sources exist after Phase 6. Dashboard is high value for operating 3+ simultaneous strategies but has no blocking dependency — implement after all pipeline stages are validated in production.
**Delivers:** Extended `interfaces/streamlit_dashboard.py` with portfolio PnL panel, per-strategy performance charts, strategy lifecycle pipeline view, discovery queue progress, open positions table.
**Uses:** `streamlit 1.55.0`, `plotly 5.x`
**Implements:** `interfaces/streamlit_dashboard.py` (extend existing stub)
**Addresses:** Monitoring dashboard (P2 differentiator)

### Phase Ordering Rationale

- **Schema first (Phase 1):** `paper` status is a prerequisite for Phases 3-7. Zero-risk, high-unlock.
- **Cost model before sweep (Phase 2 before Phase 6):** Running sweep on zero-cost backtest produces systematically overfit candidates. Phase 2 quality gates must exist before Phase 6 results are trustworthy.
- **Paper before portfolio risk (Phase 3 before Phase 4):** Portfolio risk manager needs multi-strategy position data to gate on. With only one strategy in paper, the gate has nothing to check.
- **Monitoring before full live deployment (Phase 5 before Phase 6+live):** A strategy should never reach production without degradation monitoring active.
- **Discovery last (Phase 6):** The most complex phase (multiple-comparisons risk, CPU-intensive sweep) should only run when all downstream validation infrastructure is in place to handle its output.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** Walk-forward windowing strategy — need to define specific IS/OOS window sizes, overlap policy, and minimum window count for the target timeframes (1m/5m/1h)
- **Phase 4:** `riskfolio-lib` HRP implementation details — API may differ from documentation; verify `HRPOpt` API compatibility with current portfolio structure before implementation
- **Phase 6:** Optuna integration with `ProcessPoolExecutor` — potential SQLite database locking for optuna study storage when running parallel trials; may need `optuna.storages.JournalStorage` instead of default RDB storage

Phases with standard patterns (skip research-phase):
- **Phase 1:** Schema extension + state machine — standard Python enum + Pydantic patterns, well-documented
- **Phase 3:** Paper broker extension — `PaperBroker` already exists; graduation criteria are straightforward rule evaluation
- **Phase 5:** `APScheduler` + read-only DB polling — well-documented patterns, existing scheduler in codebase
- **Phase 7:** Streamlit dashboard — existing stub, standard `st.plotly_chart` patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All package versions verified on PyPI; optuna, vectorbt, streamlit, APScheduler version numbers confirmed. One exception: riskfolio-lib MEDIUM (GitHub releases not directly confirmed, PyPI + WebSearch agreement) |
| Features | HIGH | Gap analysis from direct codebase inspection; P1 features all tied to specific missing modules; competitor analysis from official docs (freqtrade, QuantConnect) |
| Architecture | HIGH | Based on direct codebase analysis of `engine/core/ports.py`, `engine/schema.py`, `engine/backtest/runner.py`, `engine/application/trading/orchestrator.py`; all extension points verified to exist |
| Pitfalls | HIGH | Walk-forward, slippage, lookahead bias well-documented across multiple industry sources; correlation risk pitfall confirmed by multiple independent sources |

**Overall confidence:** HIGH

### Gaps to Address

- **Optuna + ProcessPoolExecutor storage conflict:** When running parallel Bayesian optimization trials with `ProcessPoolExecutor`, the default SQLite-based optuna study storage may produce locking contention. During Phase 6 planning, verify whether `optuna.storages.JournalFileStorage` or in-memory storage is needed for the sweep parallelism pattern.

- **vectorbt fill price model compatibility:** The claim that vectorbt supports `next_open` fill price simulation should be verified against `vectorbt 0.28.4` API before Phase 2 implementation. If vectorbt does not support this natively, fill price correction must happen in the `BacktestRunner` pre-processing step before feeding data to vectorbt.

- **ccxt.pro WebSocket asyncio integration:** Current codebase uses ccxt REST in a synchronous context. Integrating `ccxt.pro` watch* methods requires `asyncio` event loop management alongside the existing FastAPI async context. Potential conflict with `APScheduler`'s `BackgroundScheduler` (thread-based). During Phase 3 planning, verify whether `AsyncIOScheduler` should replace `BackgroundScheduler` to avoid event loop conflicts.

- **riskfolio-lib version API:** MEDIUM confidence. The HRP and Kelly optimization API should be verified against actual installed version before Phase 4 implementation begins. The `riskfolio-lib` 7.x API may differ from 6.x examples found in community documentation.

- **SQLite WAL mode for parallel workers:** `parallel_optimizer.py` uses `ProcessPoolExecutor`. Current SQLite + `TradeRepository` pattern is documented to break with concurrent writes from worker processes. Phase 2 and Phase 6 must use file-based results (pickle/JSON per worker) and merge after completion — verify this pattern is not already broken in the existing `parallel_optimizer.py`.

## Sources

### Primary (HIGH confidence)
- PyPI: optuna 4.7.0, vectorbt 0.28.4, streamlit 1.55.0, APScheduler 3.10+ — version numbers confirmed
- freqtrade official docs — optuna integration in production trading system confirmed
- scikit-learn official docs — AgglomerativeClustering for correlation-based grouping
- ccxt.pro manual (github.com/ccxt/ccxt) — bundled in standard ccxt, no separate install
- Direct codebase analysis: `engine/core/ports.py`, `engine/schema.py`, `engine/backtest/runner.py`, `engine/backtest/optimizer.py`, `engine/application/trading/orchestrator.py`, `engine/strategy/risk_manager.py`, `strategies/registry.json`

### Secondary (MEDIUM confidence)
- Riskfolio-Lib PyPI + readthedocs — HRP/Kelly models confirmed, GitHub releases page inaccessible
- QuantInsti — walk-forward methodology
- BreakingAlpha — portfolio-level risk constraints, correlation surge in crisis
- greyhoundanalytics.com — vectorbt vs. backtrader comparison; backtrader unmaintained since 2018
- 3commas.io — AI trading bot risk management, backtesting guide 2025

### Tertiary (LOW confidence)
- "Binance fill accuracy within 0.3%" for vectorbt PRO — single WebSearch source, PRO version not publicly installable; treat as unverified; use configurable percentage slippage as approximation
- joblib parallel backtesting patterns — WebSearch blog post, pattern confirmed but calibration numbers not independently verified

---
*Research completed: 2026-03-11*
*Ready for roadmap: yes*

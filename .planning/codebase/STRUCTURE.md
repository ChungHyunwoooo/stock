# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
02_stock/                        # Project root
├── api/                         # FastAPI REST layer
│   ├── main.py                  # App entry point, startup hooks
│   ├── dependencies.py          # FastAPI dependency injection
│   └── routers/                 # One file per resource domain
│       ├── alerts.py
│       ├── backtests.py
│       ├── bot_config.py
│       ├── knowledge.py
│       ├── regime.py
│       ├── screener.py
│       ├── strategies.py
│       └── symbols.py
├── engine/                      # Core domain engine (all business logic)
│   ├── config_path.py           # Centralized path resolution (config/ + state/)
│   ├── schema.py                # StrategyDefinition Pydantic model (system contract)
│   ├── cli.py                   # CLI entry point
│   ├── core/                    # Domain models, DB, ports (no upstream deps)
│   ├── data/                    # Market data providers and caches
│   ├── indicators/              # Technical indicator computation
│   ├── patterns/                # Chart/candle pattern recognition
│   ├── analysis/                # Direction judgment and regime
│   ├── strategy/                # Strategy rules, scanner daemon, risk
│   ├── execution/               # Order execution (paper + live brokers)
│   ├── notifications/           # Discord webhook alert dispatch
│   ├── interfaces/              # Discord bot, scanner runtime, Streamlit
│   ├── backtest/                # Historical replay and optimization
│   └── application/            # Service orchestration layer
│       └── trading/             # TradingOrchestrator, TradingControlService
│           └── providers/       # JsonStrategySource
├── strategies/                  # Strategy definitions as data files
│   ├── registry.json            # Master list of all strategies + status
│   └── {id}/                    # One dir per strategy
│       ├── definition.json      # StrategyDefinition JSON (system contract)
│       └── research.md          # Research notes (optional)
├── config/                      # Runtime configuration (not secrets)
│   ├── discord.json             # Discord webhook URLs + bot token
│   ├── discord.example.json     # Template for discord.json
│   ├── broker.json              # Exchange API keys (${ENV_VAR} references)
│   ├── broker.example.json      # Template for broker.json
│   ├── pattern_alert.json       # Scanner daemon config
│   ├── alert_runtime.json       # Alert runtime state
│   └── exchange_symbol_cache/   # Cached symbol lists per exchange
├── state/                       # Runtime state files (auto-generated)
│   ├── runtime_state.json       # TradingRuntimeState (mode, positions, orders)
│   ├── pattern_alert_sent.json  # Dedup state for scanner alerts
│   ├── positions.json           # Open positions snapshot
│   ├── discord_user_prefs.json  # Per-user Discord preferences
│   └── alert_scan_state.json    # Alert scanner state
├── tests/                       # Test suite
│   ├── conftest.py              # Shared fixtures
│   └── trading/                 # Trading-specific integration tests
├── data/                        # Data artifacts (CSVs, downloaded data)
├── deploy/                      # Deployment configs
├── docs/                        # Documentation
├── tse.db                       # SQLite database (strategies, backtests, trades)
├── pyproject.toml               # Project metadata and dependencies
└── ARCHITECTURE.md              # High-level architecture overview
```

## Directory Purposes

**`engine/core/`:**
- Purpose: Shared domain models and persistence; no dependency on other `engine/` layers
- Contains: `models.py`, `ports.py`, `db_models.py`, `repository.py`, `database.py`, `json_store.py`, `knowledge_store.py`, `knowledge_tags.py`
- Key files: `models.py` (all dataclasses), `ports.py` (Protocol interfaces), `db_models.py` (SQLAlchemy ORM)

**`engine/data/`:**
- Purpose: All market data fetching and caching
- Contains: `provider_base.py` (abstract + factory), `provider_crypto.py` (ccxt), `provider_upbit.py`, `provider_fdr.py`, `ohlcv_cache.py`, `upbit_cache.py`, `upbit_ranking.py`, `binance_ws.py`, `upbit_ws.py`
- Factory pattern: `get_provider(market_type, exchange=...)` in `provider_base.py`

**`engine/indicators/`:**
- Purpose: Numerical indicator computation; organized by indicator category
- Subdirs: `price/`, `momentum/`, `volume/`, `custom/`
- Key file: `registry.py` — maps uppercase indicator names to TA-Lib or custom callables
- Custom indicators: `engine/indicators/custom/` (`staircase_indicator`, `watermelon_indicator`)

**`engine/patterns/`:**
- Purpose: Structural and candle pattern recognition from price arrays
- Key files: `bollinger.py`, `candle_patterns.py`, `chart_patterns.py`, `key_levels.py`, `market_structure.py`, `pullback.py`, `volume_profile.py`

**`engine/analysis/`:**
- Purpose: Synthesize indicator + pattern outputs into directional verdict
- Key files: `direction.py` (weighted confidence scoring), `confluence.py`, `crypto_regime.py`, `mtf_confluence.py`

**`engine/strategy/`:**
- Purpose: Strategy detection, scanner daemon, risk management, scalping strategies
- Key files: `pattern_alert.py` (sole scanner daemon), `pattern_detector.py`, `candle_patterns.py`, `pullback_detector.py`, `condition_evaluator.py`, `strategy_evaluator.py`, `risk_manager.py`, `scalping_risk.py`, `plugin_registry.py`, `plugin_runtime.py`
- Scalping: `scalping_bb_bounce_rsi.py`, `scalping_bb_squeeze.py`, `scalping_triple_ema.py`, `scalping_ema_crossover.py`
- Spike analysis: `spike_detector.py`, `spike_leadlag_analysis.py`, `spike_precursor_analysis.py`
- Regime filters: `hmm_regime.py`, `regime_filter.py`, `oi_filter.py`

**`engine/execution/`:**
- Purpose: Order submission to paper or live exchanges
- Key files: `broker_base.py` (abstract `BaseBroker`), `paper_broker.py`, `binance_broker.py`, `upbit_broker.py`, `broker_factory.py`, `scalping_runner.py`
- Config: `config/broker.json` (API keys via `${ENV_VAR}` references)

**`engine/notifications/`:**
- Purpose: Outbound alert delivery
- Key files: `discord_webhook.py` (`DiscordWebhookNotifier`), `alert_discord.py`, `alert_positions.py`

**`engine/interfaces/`:**
- Purpose: User-facing surfaces (Discord bot, background scanner, Streamlit)
- Subdirs: `discord/` (bot + slash commands), `scanner/` (background scanner runner)
- Key files: `bootstrap.py` (wires trading runtime), `discord/control_bot.py`, `discord/commands/scanner.py`, `streamlit_dashboard.py`

**`engine/application/trading/`:**
- Purpose: Service orchestration; composes ports into usable services
- Key files: `orchestrator.py` (`TradingOrchestrator`), `trading_control.py`, `signal_scanner.py`, `strategy_monitor.py`
- Bootstrap: `engine/interfaces/bootstrap.py:build_trading_runtime()` wires everything

**`engine/backtest/`:**
- Purpose: Historical strategy validation and parameter optimization
- Key files: `runner.py`, `strategy_base.py`, `pattern_backtest.py`, `direction_predictor.py`, `metrics.py`, `optimizer.py`, `parallel_optimizer.py`

**`strategies/`:**
- Purpose: Strategy definitions as data, not code
- Layout: `registry.json` (master index) + `{id}/definition.json` per strategy
- Active strategies: `dante_staircase`, `dante_watermelon`, `sar_reversal`, `sar_adx_trend`, `sar_adx_cross`, `bb_mean_reversion`, `rsi_macd_momentum`

**`config/`:**
- Purpose: User-editable runtime config; low churn
- Secrets: API keys go in `broker.json` using `${ENV_VAR}` syntax; never hardcode

**`state/`:**
- Purpose: Auto-generated runtime state; high churn; gitignored
- Created automatically by `engine/config_path.py:state_file()`

## Key File Locations

**Entry Points:**
- `api/main.py`: FastAPI app, startup lifecycle, launches Discord bot + scanner
- `engine/strategy/pattern_alert.py`: Scanner daemon (also runnable as `__main__`)
- `engine/cli.py`: CLI utilities
- `engine/interfaces/discord/control_bot.py`: Discord bot

**Configuration:**
- `engine/config_path.py`: All path resolution — always use `config_file()` / `state_file()`
- `config/pattern_alert.json`: Scanner daemon settings (symbols, interval, cooldown)
- `config/discord.json`: Webhook URLs and bot token
- `config/broker.json`: Exchange API credentials

**Domain Contracts:**
- `engine/schema.py`: `StrategyDefinition` Pydantic model — the system-wide strategy contract
- `engine/core/models.py`: Runtime domain models (`TradingSignal`, `OrderRequest`, `ExecutionRecord`, `Position`)
- `engine/core/ports.py`: Port protocols (`BrokerPort`, `NotificationPort`, `RuntimeStorePort`)

**Core Logic:**
- `engine/strategy/pattern_alert.py`: Main analysis + alert pipeline
- `engine/analysis/direction.py`: `judge_direction()` — weighted confidence scoring
- `engine/data/provider_base.py`: `DataProvider` ABC + `get_provider()` factory
- `engine/execution/broker_base.py`: `BaseBroker` — order execution template

**Plugin Wiring:**
- `engine/strategy/plugin_runtime.py`: Registers all broker/notifier/store plugins
- `engine/interfaces/bootstrap.py`: `build_trading_runtime()` — compose full runtime

**Database:**
- `engine/core/database.py`: SQLAlchemy engine + session context manager
- `engine/core/db_models.py`: ORM models (`StrategyRecord`, `BacktestRecord`, `TradeRecord`, `OrderRecord`)
- `engine/core/repository.py`: Repository classes for each ORM model
- `tse.db`: SQLite file at project root

**Testing:**
- `tests/conftest.py`: Shared fixtures
- `tests/test_*.py`: Unit tests per module
- `tests/trading/`: Integration tests for trading flow

## Naming Conventions

**Files:**
- Pattern: `{subject}_{role}.py` — subject first, role as suffix
- Examples: `provider_crypto.py`, `broker_base.py`, `alert_discord.py`, `upbit_ranking.py`
- Roles: `_base` (ABC), `_factory` (factory function), `_cache` (caching), `_detector` (detection), `_evaluator` (evaluation), `_runner` (execution loop), `_scanner` (scanning), `_store` (persistence)
- Scalping strategies prefix: `scalping_`
- Spike analysis prefix: `spike_`

**Directories:**
- Plural concept directories: `indicators/`, `patterns/`, `providers/`, `commands/`
- Singular role directories: `core/`, `data/`, `analysis/`, `execution/`, `backtest/`

**Functions:**
- Calculation: `calc_*` (e.g., `calc_profit`)
- Detection: `detect_*` (e.g., `detect_pullback`)
- Evaluation: `evaluate_*`
- Judgment: `judge_*` (e.g., `judge_direction`)
- Fetching: `fetch_*` (e.g., `fetch_ohlcv`, `fetch_balance`)
- Building: `build_*` (e.g., `build_trading_runtime`)
- Prediction: `predict_*` (e.g., `predict_multi`, `predict_momentum`)
- Private helpers: `_` prefix (e.g., `_analyze_tf`, `_scan_once`)

**Vocabulary:**
- `indicator` — numerical value from price data
- `pattern` — structural recognition result
- `signal` — trading action decision
- `alert` — outbound notification

## Where to Add New Code

**New Strategy Definition:**
1. Create `strategies/{id}/definition.json` (validated by `engine/schema.py:StrategyDefinition`)
2. Add entry to `strategies/registry.json`
3. Optionally add `strategies/{id}/research.md`

**New Exchange/Data Provider:**
1. Implement `engine/data/provider_{exchange}.py` subclassing `DataProvider`
2. Register in `engine/data/provider_base.py:get_provider()` factory

**New Broker:**
1. Implement `engine/execution/{exchange}_broker.py` subclassing `BaseBroker`
2. Override: `_place_order`, `_fetch_raw_balance`, `_fetch_raw_positions`, `_cancel_raw`, `_convert_symbol`
3. Register in `engine/strategy/plugin_runtime.py`: `broker_plugins.register("name", factory)`
4. Add to `engine/execution/broker_factory.py:create_broker()`

**New Technical Indicator:**
1. Add computation to appropriate subdir: `engine/indicators/{price|momentum|volume|custom}/`
2. Register in `engine/indicators/registry.py:INDICATOR_REGISTRY`

**New Chart/Candle Pattern:**
- Chart patterns: `engine/patterns/chart_patterns.py`
- Candle patterns: `engine/patterns/candle_patterns.py` or `engine/strategy/candle_patterns.py`

**New Scalping Strategy:**
1. Create `engine/strategy/scalping_{name}.py`
2. Follow the pattern of existing scalping strategies

**New Discord Slash Command:**
1. Create or extend a command plugin in `engine/interfaces/discord/commands/`
2. Register in `engine/interfaces/discord/control_bot.py`

**New API Endpoint:**
1. Add router to `api/routers/{domain}.py`
2. Register in `api/main.py`: `app.include_router(router, prefix="/api")`

**New Config Key:**
- Scanner config: Add field to `PatternAlertConfig` dataclass in `engine/strategy/pattern_alert.py`
- Runtime config: Persist via `engine/config_path.py:config_file()` / `state_file()`

**New Utility/Helper:**
- Path utilities: `engine/config_path.py`
- Shared engine utilities: `engine/{relevant_layer}/` matching subject+role naming

## Special Directories

**`state/`:**
- Purpose: Auto-generated JSON runtime state files
- Generated: Yes (created by `engine/config_path.py:state_file()`)
- Committed: No (runtime-only; should be gitignored)

**`config/exchange_symbol_cache/`:**
- Purpose: Cached symbol lists fetched from exchange APIs at startup
- Generated: Yes (`warm_exchange_symbol_caches()` in `api/main.py`)
- Committed: Optional (speeds up cold start)

**`engine/interfaces/discord/cache/`:**
- Purpose: Discord bot internal cache
- Generated: Yes
- Committed: No

**`data/`:**
- Purpose: Downloaded market data, CSV exports
- Generated: Yes (backtest/research artifacts)
- Committed: No

**`deploy/`:**
- Purpose: Deployment configuration files
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-03-11*

# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Layered Pipeline Architecture with Port/Adapter (Hexagonal) core

**Key Characteristics:**
- Strict unidirectional data flow: OHLCV → indicators → patterns → analysis → signal → alert
- Port/Protocol interfaces in `engine/core/ports.py` decouple execution, notification, and storage
- Plugin registry pattern for broker/notifier/store wiring at runtime
- Strategy definitions are data (JSON), not code — loaded from `strategies/*/definition.json`
- Dual scanner architecture: automated daemon (`pattern_alert.py`) + Discord slash command interface

## Layers

**core/ — Domain Models & Persistence:**
- Purpose: Shared data contracts, database, repositories, ports (interfaces)
- Location: `engine/core/`
- Contains: `models.py` (dataclasses), `ports.py` (Protocol interfaces), `db_models.py` (SQLAlchemy ORM), `repository.py` (data access), `database.py` (SQLite engine), `json_store.py` (JSON runtime state)
- Depends on: nothing inside `engine/`
- Used by: all other layers

**data/ — Market Data Acquisition:**
- Purpose: Fetch OHLCV from exchanges/APIs; cache management; WebSocket real-time feeds
- Location: `engine/data/`
- Contains: `provider_base.py` (abstract `DataProvider`), `provider_crypto.py` (ccxt/Binance), `provider_upbit.py`, `provider_fdr.py` (KR/US stocks), `ohlcv_cache.py`, `upbit_cache.py`, `upbit_ranking.py`, `binance_ws.py`, `upbit_ws.py`
- Key factory: `get_provider(market_type, exchange=...)` in `provider_base.py`
- Depends on: `engine/core/` (schema)
- Used by: `indicators/`, `strategy/`, `backtest/`

**indicators/ — Numerical Calculation:**
- Purpose: Compute technical indicator values from OHLCV arrays
- Location: `engine/indicators/`
- Contains: `registry.py` (TA-Lib mapping + custom), `price/`, `momentum/`, `volume/`, `custom/` subdirs
- Key abstraction: `INDICATOR_REGISTRY` dict mapping uppercase names (e.g. `"RSI"`) to callables
- Custom indicators: `staircase_indicator`, `watermelon_indicator` in `engine/indicators/custom/`
- Depends on: TA-Lib, pandas, numpy
- Used by: `patterns/`, `strategy/`, `backtest/`

**patterns/ — Structure Recognition:**
- Purpose: Identify chart/candle patterns and market structure from indicator outputs
- Location: `engine/patterns/`
- Contains: `bollinger.py`, `candle_patterns.py`, `chart_patterns.py`, `key_levels.py`, `market_structure.py`, `pullback.py`, `smc.py`, `trend_strength.py`, `volume_profile.py`
- Depends on: `indicators/`
- Used by: `analysis/`, `strategy/`

**analysis/ — Direction Judgment:**
- Purpose: Combine indicator + pattern outputs into a directional verdict with confidence score
- Location: `engine/analysis/`
- Contains: `direction.py` (weighted scoring: signal 20% + trend 30% + volume 20% + key_levels 15% + candle 15%), `confluence.py`, `crypto_regime.py`, `mtf_confluence.py`, `exchange_dominance.py`, `sector_regime.py`, `cross_exchange.py`
- Key function: `judge_direction(base, adx, volume, structure, candle, key_levels, side)` → `{direction, confidence, breakdown, reasons}`
- Depends on: `patterns/`, `indicators/`
- Used by: `strategy/`

**strategy/ — Strategy Rules & Signal Generation:**
- Purpose: Apply strategy rules, detect signals, manage risk, run the scanner loop
- Location: `engine/strategy/`
- Key files:
  - `pattern_alert.py` — sole automated scanner daemon (threading loop, 30s interval)
  - `pattern_detector.py` — structural pattern scan (double bottom/top, triangles)
  - `candle_patterns.py` — TA-Lib candle pattern scan
  - `pullback_detector.py` — pullback/retracement detection
  - `condition_evaluator.py` — evaluates JSON `ConditionGroup` against DataFrame
  - `strategy_evaluator.py` — evaluates full `StrategyDefinition`
  - `risk_manager.py` / `scalping_risk.py` — position limits, daily loss, consecutive SL
  - `plugin_registry.py` — generic `PluginRegistry[T]`
  - `plugin_runtime.py` — wires broker/notifier/store plugins at startup
  - `scheduler.py` — cron-style scheduling
  - Scalping strategies: `scalping_bb_bounce_rsi.py`, `scalping_bb_squeeze.py`, `scalping_triple_ema.py`, `scalping_ema_crossover.py`
  - Spike analysis: `spike_detector.py`, `spike_leadlag_analysis.py`, `spike_precursor_analysis.py`
- Depends on: all upstream layers
- Used by: `execution/`, `interfaces/`, `notifications/`

**execution/ — Order Execution:**
- Purpose: Submit orders to exchanges (paper or live), record trades
- Location: `engine/execution/`
- Contains: `broker_base.py` (abstract `BaseBroker`), `paper_broker.py`, `binance_broker.py`, `upbit_broker.py`, `broker_factory.py`, `scalping_runner.py`
- `BaseBroker` template: validate → convert symbol → `_place_order()` → update position → return `ExecutionRecord`
- Abstract methods per broker: `_place_order`, `_fetch_raw_balance`, `_fetch_raw_positions`, `_cancel_raw`, `_convert_symbol`
- Depends on: `engine/core/models.py`
- Used by: `application/`

**notifications/ — Alert Dispatch:**
- Purpose: Send trade signals, pending orders, execution records via Discord webhook
- Location: `engine/notifications/`
- Contains: `discord_webhook.py` (`DiscordWebhookNotifier`), `alert_discord.py`, `alert_bot_config.py`, `alert_positions.py`
- Implements: `NotificationPort` protocol from `engine/core/ports.py`
- Depends on: `engine/core/models.py`

**application/ — Service Layer:**
- Purpose: Orchestrate domain operations; compose ports for the trading runtime
- Location: `engine/application/trading/`
- Key files:
  - `orchestrator.py` (`TradingOrchestrator`) — signal → pending/execute/alert based on `TradingMode`
  - `trading_control.py` (`TradingControlService`) — approve/reject pending, pause/resume
  - `signal_scanner.py`, `strategy_monitor.py` — scanning & monitoring services
  - `providers/` — `JsonStrategySource` loads strategy definitions from `strategies/`
- Bootstrap: `engine/interfaces/bootstrap.py` → `build_trading_runtime()` wires all ports via `plugin_runtime.py`
- Depends on: `engine/core/ports.py`, concrete broker/notifier/store implementations

**interfaces/ — User-Facing Entry Points:**
- Purpose: Expose functionality to Discord bot, scanner daemon, Streamlit dashboard
- Location: `engine/interfaces/`
- Contains:
  - `discord/control_bot.py` — Discord bot (slash commands)
  - `discord/commands/` — command plugins: `scanner.py`, `pattern.py`, `analysis.py`, `orders.py`, `runtime.py`, `base.py`
  - `scanner/alert_scanner_runtime.py` — wraps `pattern_alert` loop for background startup
  - `streamlit_dashboard.py` — Streamlit UI
- Depends on: `application/`, `strategy/`

**backtest/ — Historical Validation:**
- Purpose: Replay strategies over historical OHLCV; report metrics; optimize parameters
- Location: `engine/backtest/`
- Contains: `runner.py`, `strategy_base.py`, `pattern_backtest.py`, `direction_predictor.py`, `metrics.py`, `report.py`, `optimizer.py`, `parallel_optimizer.py`
- Depends on: `data/`, `indicators/`, `strategy/`

**api/ — REST API:**
- Purpose: FastAPI HTTP interface for strategy management, backtests, knowledge, screener
- Location: `api/`
- Entry point: `api/main.py` (FastAPI app, CORS, startup hooks)
- Routers: `alerts`, `backtests`, `bot_config`, `knowledge`, `regime`, `screener`, `strategies`, `symbols`
- On startup: `init_db()`, `warm_exchange_symbol_caches()`, Discord bot background, alert scanner background

## Data Flow

**Automated Scanner Flow:**

1. `api/main.py` startup → `run_alert_scanner_background()` → `engine/interfaces/scanner/alert_scanner_runtime.py`
2. Scanner calls `engine/strategy/pattern_alert.py:start()` → spawns daemon thread (`pattern-alert`)
3. Every 30s: `_scan_once()` → resolves symbols (Upbit ranking or config)
4. Per symbol: `analyze_symbol(symbol, config)` → per timeframe: `_analyze_tf()`
5. `_analyze_tf()` calls:
   - `get_provider()` → fetch OHLCV DataFrame
   - `predict_multi()` → direction vote (momentum + EMA cross + structure)
   - `scan_patterns()` → structural patterns (double bottom, triangle, etc.)
   - `scan_candle_patterns()` → TA-Lib candle patterns
   - `detect_pullback()` → pullback signal
6. Returns `list[TFResult]` → `_is_alertable()` check → cooldown check
7. `_build_message()` → `_generate_chart()` → `_send_discord(webhook)`

**Trading Signal Flow (TradingOrchestrator):**

1. External caller invokes `TradingOrchestrator.process_signal(signal, quantity)`
2. Load `TradingRuntimeState` from `RuntimeStorePort`
3. Branch on `TradingMode`:
   - `alert_only` → `NotificationPort.send_signal()` only
   - `semi_auto` → create `PendingOrder`, notify, save state
   - `auto` → `BrokerPort.execute_order()` → `ExecutionRecord` → notify, save state

**Strategy Definition → Evaluation Flow:**

1. JSON strategy files: `strategies/{id}/definition.json` validated by `engine/schema.py:StrategyDefinition`
2. `condition_evaluator.py` evaluates `ConditionGroup` (AND/OR logic) against computed indicator columns
3. `strategy_evaluator.py` composes full strategy entry/exit logic
4. Results feed into signal generation

**State Management:**
- Runtime trading state: `state/runtime_state.json` (loaded/saved via `JsonRuntimeStore`)
- Scanner dedup state: `state/pattern_alert_sent.json`
- Bot config: `config/discord.json`, `config/pattern_alert.json`, `config/broker.json`
- Persistent trade records: `tse.db` (SQLite via SQLAlchemy)

## Key Abstractions

**DataProvider (`engine/data/provider_base.py`):**
- Purpose: Uniform OHLCV fetch interface across all exchanges/markets
- Factory: `get_provider(market_type, exchange=...)` → returns concrete provider
- All providers return `pd.DataFrame` with columns `open, high, low, close, volume` and `DatetimeIndex`

**BaseBroker (`engine/execution/broker_base.py`):**
- Purpose: Exchange-agnostic order lifecycle (validate → place → position update)
- Concrete implementations: `PaperBroker`, `BinanceBroker`, `UpbitBroker`
- Template method: `execute_order()` is final; subclasses override `_place_order()`, `_fetch_raw_balance()`, etc.

**Port Protocols (`engine/core/ports.py`):**
- `RuntimeStorePort` — load/save `TradingRuntimeState`
- `NotificationPort` — send signal/pending/execution/text
- `BrokerPort` — execute order, fetch balance/positions, cancel
- All are `typing.Protocol` (structural subtyping, no inheritance required)

**PluginRegistry (`engine/strategy/plugin_registry.py`):**
- Generic `PluginRegistry[T]` mapping string names to factory callables
- Three registries: `broker_plugins`, `notifier_plugins`, `runtime_store_plugins` in `engine/strategy/plugin_runtime.py`
- Add new broker: `broker_plugins.register("my_exchange", lambda **_: MyBroker())`

**StrategyDefinition (`engine/schema.py`):**
- Pydantic model: the system-wide contract for all strategies
- Fields: `name`, `markets`, `direction`, `timeframes`, `indicators` (list of `IndicatorDef`), `entry`/`exit` (`ConditionGroup`), `risk` (`RiskParams`), `regime` (`RegimeConfig`)
- Stored as JSON in `strategies/{id}/definition.json`

**PatternAlertConfig (`engine/strategy/pattern_alert.py`):**
- Dataclass config for the scanner daemon
- Persisted to `config/pattern_alert.json`; loaded at daemon start and on Discord `/설정` command

## Entry Points

**FastAPI Server:**
- Location: `api/main.py`
- Triggers: HTTP requests; also launches Discord bot and alert scanner on startup
- Responsibilities: REST API, startup lifecycle management

**Pattern Alert Daemon:**
- Location: `engine/strategy/pattern_alert.py`
- Triggers: `start()` call from `api/main.py` startup or Discord `/자동시작` command
- Responsibilities: Continuous symbol scanning, multi-TF analysis, Discord alert dispatch

**Discord Bot:**
- Location: `engine/interfaces/discord/control_bot.py`
- Triggers: `run_bot_background()` from `api/main.py` startup
- Responsibilities: Slash command handling, manual scan, trading control (approve/reject orders)

**CLI:**
- Location: `engine/cli.py`
- Triggers: Direct command-line invocation
- Responsibilities: Admin utilities, manual operations

**Direct Script:**
- Location: `engine/strategy/pattern_alert.py` (`if __name__ == "__main__"`)
- Triggers: `python -m engine.strategy.pattern_alert`
- Responsibilities: Standalone scanner without FastAPI

## Error Handling

**Strategy:** try/except per symbol in `_scan_once()`; errors are logged, other symbols continue

**Patterns:**
- Per-timeframe errors caught in `_analyze_tf()`: log and return `None`
- Per-symbol errors in `_scan_once()`: `logger.error(..., exc_info=True)`, loop continues
- Provider errors in `DataProvider.fetch_ohlcv()`: propagate to caller
- Broker order validation raises `ValueError` before API call

## Cross-Cutting Concerns

**Logging:** `logging.getLogger(__name__)` per module; no centralized log config in engine (set by caller)

**Path Management:** `engine/config_path.py` centralizes all config/state paths; use `config_file(name)` and `state_file(name)` — never hardcode paths

**Validation:** Pydantic for strategy definitions (`engine/schema.py`); dataclasses with manual validation for runtime models (`engine/core/models.py`)

**Concurrency:** Scanner daemon runs in background `threading.Thread`; Discord bot uses `asyncio.to_thread()` to call sync engine functions from async slash command handlers

---

*Architecture analysis: 2026-03-11*

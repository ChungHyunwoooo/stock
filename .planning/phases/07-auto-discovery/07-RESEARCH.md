# Phase 7 Research: Auto-Discovery

## 1. Strategy Registry System

**Registry:** `strategies/registry.json` -- flat JSON array under `"strategies"` key.
Each entry has: `id`, `name`, `status`, `direction`, `timeframe`, `regime`, `definition` (path to definition.json), optional `status_history`.

**LifecycleManager** (`engine/strategy/lifecycle_manager.py`):
- `register(entry: dict)` -- forces status=draft, appends status_history, atomic write via tempfile+rename
- `transition(strategy_id, target, reason, gate, gate_config, session)` -- FSM enforcement
- `list_by_status(status)` -- filter by status string
- Transition map: draft->testing->paper->active->archived (with some backwards allowed)

**StrategyDefinition** (`engine/schema.py`):
- Pydantic BaseModel: name, version, status, markets, direction, timeframes, indicators (list[IndicatorDef]), entry/exit (ConditionGroup), risk (RiskParams), metadata, regime
- `IndicatorDef`: name (ta-lib name), params (dict), output (str or dict)
- `ConditionGroup`: logic (and/or), conditions (list[Condition] with left/op/right)

**Definition JSON** (e.g. `strategies/ref_rsi_divergence/definition.json`):
- Matches StrategyDefinition schema exactly
- indicators array with name/params/output
- entry/exit with logic + conditions

## 2. Backtest Infrastructure

**BacktestRunner** (`engine/backtest/runner.py`):
- `run(strategy, symbol, start, end, timeframe, initial_capital, market, regime_enabled)` -> BacktestResult
- Uses `get_provider(market_type)` for data, `StrategyEngine.generate_signals()` for signals
- Returns BacktestResult with sharpe_ratio, max_drawdown, total_return, trades, equity_curve
- Supports SlippageModel injection, fee_rate, auto_save to DB

**WalkForwardValidator** (`engine/backtest/walk_forward.py`):
- `validate(equity_curve)` -> ValidationResult
- n_windows=5, train_pct=0.7, gap_threshold=0.5
- Returns ValidationResult with per-window IS/OOS Sharpe + overall_passed

**MultiSymbolValidator** (`engine/backtest/multi_symbol.py`):
- `validate(strategy, symbols, start, end, ...)` -> MultiSymbolResult
- ProcessPoolExecutor parallel backtest
- median Sharpe gate (threshold=0.5)
- `select_uncorrelated_symbols()` for greedy correlation-based selection

**ValidationResult** (`engine/backtest/validation_result.py`):
- WindowResult: window_idx, is_sharpe, oos_sharpe, gap_ratio, passed
- ValidationResult: mode, windows, overall_passed, summary

## 3. Indicator System

**Registry** (`engine/indicators/registry.py`):
- `INDICATOR_REGISTRY: dict[str, Callable]` -- maps uppercase names to ta-lib abstract functions
- 17 built-in indicators: RSI, MACD, BBANDS, EMA, SMA, STOCH, ATR, ADX, CCI, OBV, WILLR, MFI, DEMA, TEMA, SAR, PLUS_DI, MINUS_DI
- 2 custom: STAIRCASE, WATERMELON
- `get_indicator(name)` lookup

**Compute** (`engine/indicators/compute.py`):
- `compute_indicator(df, indicator_def)` -- handles single/multi output
- `compute_all_indicators(df, indicators)` -- sequential computation

## 4. Exchange Integration

**DataProvider** (`engine/data/provider_base.py`):
- ABC with `fetch_ohlcv(symbol, start, end, timeframe)` -> DataFrame
- `get_provider(market_type, **kwargs)` factory -- already supports exchange kwarg
- CryptoProvider already uses ccxt and supports binance/bybit/okx/upbit

**CryptoProvider** (`engine/data/provider_crypto.py`):
- Already ccxt-based! `_build_exchange(exchange)` creates ccxt.Exchange
- `_DEFAULT_EXCHANGES = ["binance", "bybit", "okx", "upbit"]` -- bybit/okx already listed
- `load_exchange_symbols(exchange)` with caching
- fetch_ohlcv with pagination (limit=1000 loop)

**BrokerBase** (`engine/execution/broker_base.py`):
- ABC: `_place_order`, `_fetch_raw_balance`, `_fetch_raw_positions`, `_cancel_raw`, `_convert_symbol`
- Common: execute_order, fetch_balance, cancel_order, calc_profit

**BinanceBroker** (`engine/execution/binance_broker.py`):
- ccxt-based (ccxt.binance / ccxt.binanceusdm)
- Supports spot/futures, testnet

**BrokerFactory** (`engine/execution/broker_factory.py`):
- `create_broker(exchange, market_type, testnet, config_path)` -- reads config/broker.json
- Currently supports: paper, binance, upbit
- `_SUPPORTED = {"binance", "upbit"}` -- needs extension

**PaperBroker** (`engine/execution/paper_broker.py`):
- DB-backed balance/snapshot persistence
- strategy_id scoped

## 5. Notifications

**DiscordWebhookNotifier** (`engine/notifications/discord_webhook.py`):
- `send_text(message, timeframe)` -- simple text message
- `send_signal(signal, mode_label)` -- embed with chart
- Uses config/discord.json or DISCORD_WEBHOOK_URL env var
- `_post(payload, timeframe, chart_data)` -- HTTP POST

**NotificationPort** (`engine/core/ports.py`):
- Protocol: send_signal, send_pending, send_execution, send_text

## 6. Key Findings for Phase 7

### DISC-01 (IndicatorSweeper):
- All building blocks exist: INDICATOR_REGISTRY, BacktestRunner, WalkForwardValidator, MultiSymbolValidator, LifecycleManager.register()
- StrategyDefinition is Pydantic -- can be programmatically constructed from indicator combos + params
- Optuna TPE sampler will select indicator params; search space = indicator names from INDICATOR_REGISTRY + their param ranges
- Walk-forward + multi-symbol validation already implemented -- just wire them as Optuna objective
- DiscordWebhookNotifier.send_text() for completion notification
- STATE.md blocker: "Optuna + ProcessPoolExecutor SQLite lock conflict -- JournalFileStorage needed" -- use optuna.storages.JournalFileStorage

### DISC-02 (Multi-exchange):
- CryptoProvider ALREADY supports bybit/okx via ccxt! Data side is nearly done.
- BrokerFactory needs extension: add bybit/okx to _SUPPORTED, create CcxtBroker generic class
- BinanceBroker is ccxt-based but hardcoded to binance -- can be generalized to CcxtBroker
- PaperBroker already works exchange-agnostic
- config/broker.json needs bybit/okx entries

### Architecture decisions:
- Optuna storage: JournalFileStorage (not SQLite) to avoid ProcessPoolExecutor lock
- CcxtBroker: generalize BinanceBroker into exchange-agnostic ccxt broker
- IndicatorSweeper output: StrategyDefinition JSON + LifecycleManager.register() as draft

# Phase 5 Research: Performance Monitoring

## Codebase Analysis

### Trade History Access
- `TradeRecord` in `engine/core/db_models.py`: closed trades have `strategy_name`, `profit_pct`, `profit_abs`, `exit_at`, `status`
- `TradeRepository.list_closed(strategy_name=..., broker=..., limit=N)`: returns closed trades ordered by `exit_at desc`
- `TradeRepository.summary(strategy_name=...)`: returns `win_rate`, `total`, `wins`, `losses`, `avg_profit_pct`

### Backtest Baseline
- `BacktestRecord` in `engine/core/db_models.py`: has `sharpe_ratio`, `strategy_id`, `result_json` (contains full metrics)
- `BacktestRepository.get_history(strategy_id, limit)`: returns time-ordered history (newest first)
- Baseline = most recent backtest record for the strategy

### Existing Notification System
- `DiscordWebhookNotifier` implements `NotificationPort` protocol
- `send_text(message, timeframe=None)` -- plain text to webhook
- `_post(payload, timeframe=None, chart_data=None)` -- supports embeds with color/fields
- Config: `config/discord.json` or `DISCORD_WEBHOOK_URL` env var
- Timeframe routing: `webhooks.tf_{timeframe}` key in config

### Pause Mechanism
- `TradingRuntimeState.paused` is GLOBAL (all strategies)
- `TradingControlService.pause()` / `resume()` toggle global flag
- `TradingOrchestrator.process_signal()` checks `state.paused` at top -- skips all signals
- NO per-strategy pause exists yet
- Need: per-strategy pause via `paused_strategies: set[str]` in state, or registry.json status change

### Per-Strategy Pause Design Decision
- Option A: Add `paused_strategies: set[str]` to `TradingRuntimeState` + check in Orchestrator
- Option B: Use `LifecycleManager.transition(strategy_id, "paper")` to demote active->paper
- Option A chosen: lighter weight, reversible without promotion gate re-evaluation, matches "temporary pause" semantics
- Orchestrator checks `signal.strategy_id in state.paused_strategies` before processing

### Scheduler
- APScheduler NOT in dependencies
- stdlib `threading.Timer` or `asyncio` loop sufficient for single 15-min interval
- Decision: use `threading.Thread` daemon with `time.sleep(900)` loop -- zero new dependencies, crash-safe (daemon dies with main process)
- Monitor runs in separate thread, reads DB (read-only), writes Discord alerts and paused_strategies state
- Monitor crash does NOT affect TradingOrchestrator (success criteria #3)

### Sharpe Calculation (Rolling Window)
- From closed trades `profit_pct` series:
  - mean_return = mean(profit_pct_array)
  - std_return = std(profit_pct_array)
  - sharpe = mean_return / std_return * sqrt(N_annualize)
- For trade-based (not daily): annualization factor depends on avg trade frequency
- Simpler: raw Sharpe without annualization for comparison (same window size = comparable)

### Key Interfaces Needed

```python
# Monitor reads from DB (read-only)
TradeRepository.list_closed(strategy_name=sid, broker="live", limit=30)
BacktestRepository.get_history(strategy_id, limit=1)  # latest baseline

# Monitor writes alerts via NotificationPort
notifier.send_text(message)

# Monitor pauses strategy via RuntimeStorePort
state.paused_strategies.add(strategy_id)
runtime_store.save(state)
```

## Architecture

```
StrategyPerformanceMonitor (separate thread)
  |-- reads: TradeRepository (closed trades per strategy)
  |-- reads: BacktestRepository (baseline metrics)
  |-- reads: LifecycleManager.list_by_status("active")
  |-- writes: NotificationPort.send_text() for alerts
  |-- writes: RuntimeStorePort (paused_strategies for CRITICAL)
  |
  +-- fully decoupled from TradingOrchestrator
```

## Risk: Insufficient Trade Data
- New strategies may have < 20 closed trades
- Decision: skip monitoring for strategies with < min_trades, log warning
- Matches Phase 4 pattern: "Data < 10 points treated as corr=0"

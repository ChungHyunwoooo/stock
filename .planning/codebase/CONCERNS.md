# Codebase Concerns

**Analysis Date:** 2026-03-11

---

## Tech Debt

**Global mutable state in service modules:**
- Issue: Multiple modules use module-level globals with `global` keyword to manage running state, introducing implicit shared state and making testing/isolation difficult.
- Files: `engine/strategy/pattern_alert.py` (lines 54–60, 480, 547, 621, 645, 665, 726), `engine/strategy/scheduler.py` (73, 132, 149, 185), `engine/interfaces/discord/control_bot.py` (71, 83, 98), `engine/strategy/funding.py` (24), `engine/strategy/oi_filter.py` (27), `engine/data/provider_crypto.py` (91), `engine/interfaces/scanner/alert_scanner_runtime.py` (20, 30)
- Impact: Race conditions possible when start/stop called concurrently; state leaks between test runs; no dependency injection path.
- Fix approach: Convert to class instances with explicit lifecycle methods; inject as singletons at the application entry point.

**`ScalpingRunner` imports 14+ engine modules directly:**
- Issue: `engine/execution/scalping_runner.py` (lines 30–52) imports from `broker_factory`, `broker_base`, `binance_broker`, `risk_manager`, `database`, `db_models`, `repository`, `pattern_detector`, `scalping_ema_crossover`, `scalping_risk`, `pullback_detector`, `funding`, `symbol_screener`, `scalping_bb_squeeze`, `scalping_bb_bounce_rsi`, `scalping_triple_ema`, `regime_filter`, `alert_discord` — 18 imports in total.
- Files: `engine/execution/scalping_runner.py`
- Impact: Any change in any of those modules can break the runner; unit testing requires mocking 18 dependencies; violates single-responsibility.
- Fix approach: Introduce a `ScalpingContext` dataclass to pass pre-built collaborators; extract signal evaluation to a dedicated `SignalEvaluator` class.

**`pattern_alert.py` is a God Object (757 lines):**
- Issue: Contains config dataclass, KRW rate fetching, chart generation, Discord sending, state persistence, scan loop, and start/stop lifecycle all in one file.
- Files: `engine/strategy/pattern_alert.py`
- Impact: Exceeds the project's own 300-line split threshold; hard to test individual concerns; any bug hunt requires scanning the entire file.
- Fix approach: Extract chart generation → `engine/notifications/alert_chart.py`, KRW rate → `engine/data/fx_rate.py`, scan loop → `engine/strategy/pattern_scan_loop.py`.

**`upbit_cache.py` exceeds 300-line guideline at 789 lines:**
- Issue: Single file combines in-memory cache, file-system cache, rate limiting, thread-pool management, and OHLCV transformation.
- Files: `engine/data/upbit_cache.py`
- Impact: Complex interdependencies between the two cache layers make it fragile; `_fetch_lock` and `_lock` used inconsistently across the 789 lines.
- Fix approach: Separate `MemoryCache`, `FileCache`, and `RateLimitedFetcher` into distinct classes or files.

**Hardcoded `confidence: 0.7` in scalping signal adapter:**
- Issue: `_to_pattern_signal()` in `engine/execution/scalping_runner.py` line 73 always sets `"confidence": 0.7` regardless of actual signal quality.
- Files: `engine/execution/scalping_runner.py`
- Impact: `RiskManager.allow_entry` receives a fake confidence score; risk decisions are not data-driven for scalping signals.
- Fix approach: Propagate actual confidence from `ScalpResult` or compute from ATR percentile via `ScalpRiskResult`.

**Hardcoded `entry_price=0` in spike detector signals:**
- Issue: `engine/strategy/spike_detector.py` lines 228, 302 emit signals with `entry_price=0` explicitly.
- Files: `engine/strategy/spike_detector.py`
- Impact: Downstream consumers that divide by `entry_price` will either crash or produce incorrect PnL; TP/TP calculation at lines 341–347 would be 0 * multiplier = 0.
- Fix approach: Resolve entry price from the current bar's close before constructing the signal; add a guard in `PatternSignal` to reject zero entry price.

**`engine/cli.py` at 732 lines with lazy imports inside command functions:**
- Issue: Multiple `from engine.schema import ...` and `from engine.interfaces.discord.control_bot import ...` imports are deferred inside function bodies (lines 48, 67, 140, 721), masking import errors until runtime.
- Files: `engine/cli.py`
- Impact: Import failures surface as CLI runtime errors rather than startup errors; makes static analysis blind to those dependencies.
- Fix approach: Move imports to module top-level; split the CLI into sub-modules per command group (backtest, scalping, discord, scanner).

---

## Known Bugs

**`_fetch_raw_balance` returns `unrealized_pnl: 0.0` unconditionally for futures:**
- Symptoms: Futures account equity shown without unrealized PnL component; portfolio value underreported when positions are open.
- Files: `engine/execution/binance_broker.py` (lines 119, 130)
- Trigger: Any call to `get_balance()` on an open futures position.
- Workaround: None currently; the comment at line 119 notes "ccxt에서 별도 조회 필요" but the call is never made.

**`_fetch_raw_positions` returns `entry_price: 0` for spot holdings:**
- Symptoms: Spot broker positions show zero entry price; PnL calculations will be incorrect.
- Files: `engine/execution/binance_broker.py` (line 145)
- Trigger: Any spot balance check with non-zero coin holdings.
- Workaround: None.

**`stop_loss` fallback of `entry_price * 0.98` used without data validation:**
- Symptoms: If `signal.stop_loss` is `None`, charts use a fixed 2% fallback regardless of ATR or strategy parameters.
- Files: `engine/application/trading/charts.py` (line 84)
- Trigger: Any signal without an explicit stop_loss.
- Workaround: None.

**DB engine created relative to working directory (`sqlite:///tse.db`):**
- Symptoms: Database file location changes depending on from where the process is launched; different invocations may read/write different DB files.
- Files: `engine/core/database.py` (lines 14, 34), `engine/cli.py` (lines 87, 136)
- Trigger: Running `python -m engine.execution.scalping_runner` from a different directory than project root.
- Workaround: Always run from project root; no programmatic safeguard exists.

---

## Security Considerations

**Discord bot token read from plain JSON file:**
- Risk: `config/discord.json` contains `bot_token` in cleartext. File is not in `.gitignore` by default.
- Files: `engine/interfaces/discord/control_bot.py` (lines 26–33), `config/discord.json`
- Current mitigation: Env var `DISCORD_BOT_TOKEN` is checked first; JSON fallback exists.
- Recommendations: Remove JSON token fallback entirely; require env var only; add `config/discord.json` to `.gitignore` explicitly.

**Binance API keys stored in `config/broker.json`:**
- Risk: `config/broker.json` holds `api_key` and `secret` fields. File committed to repo would expose live trading credentials.
- Files: `engine/execution/broker_factory.py` (lines 66–67), `config/broker.json`
- Current mitigation: `_resolve_env()` allows env var indirection via `${ENV_VAR}` syntax.
- Recommendations: Enforce env-var-only mode for live credentials; add pre-commit hook to block committing `config/broker.json` with real values.

**`requests` call without timeout in `pattern_alert.py`:**
- Risk: The KRW rate fetch via `requests` in `engine/strategy/pattern_alert.py` (line 29 import, used in `_get_krw_rate`) has no timeout parameter, allowing the scan thread to block indefinitely.
- Files: `engine/strategy/pattern_alert.py`
- Current mitigation: None.
- Recommendations: Set `timeout=(5, 10)` on all `requests.get` / `requests.post` calls; wrap Discord webhook sends similarly in `engine/notifications/alert_discord.py`.

---

## Performance Bottlenecks

**Blocking `time.sleep` in scan threads:**
- Problem: `engine/strategy/pattern_alert.py` scan loop uses `time.sleep(1)` in tight loop (lines 637, 755); `engine/execution/scalping_runner.py` uses `time.sleep(self._check_interval)` (30s default) blocking the runner thread.
- Files: `engine/strategy/pattern_alert.py`, `engine/execution/scalping_runner.py`, `engine/data/upbit_cache.py` (lines 254, 279, 607, 676)
- Cause: Threading model uses blocking sleep rather than event-driven wakeup; cannot be interrupted cleanly on shutdown.
- Improvement path: Replace with `threading.Event.wait(timeout=...)` so shutdown signals interrupt sleep immediately.

**`load_markets()` called inside `load_market_info` on every cache miss:**
- Problem: `engine/execution/binance_broker.py` line 232 calls `self._exchange.load_markets()` (a full REST round-trip) each time a new symbol is queried.
- Files: `engine/execution/binance_broker.py`
- Cause: No bulk-preload at broker initialisation; per-symbol lazy loading under thread contention creates N sequential REST calls.
- Improvement path: Call `load_markets()` once at `__init__` and store; use `_market_info_cache` exclusively after that.

**`backtest/pattern_backtest.py` at 757 lines with 6 near-identical backtest functions:**
- Problem: Six functions (`run_bull_bear_flag_backtest`, `run_triangle_backtest`, etc.) share 80%+ of their body, repeated 6× with minor pattern-name differences.
- Files: `engine/backtest/pattern_backtest.py`
- Cause: Copy-paste expansion rather than parameterisation.
- Improvement path: Extract a single `run_pattern_backtest(pattern_name, ...)` function; pass pattern name as a parameter.

---

## Fragile Areas

**`pattern_alert.py` scan thread — no crash isolation per symbol:**
- Files: `engine/strategy/pattern_alert.py` (lines 104, 123, 229, 254, 280, 471, 484, 501)
- Why fragile: The outer `except Exception` at line 104 silently continues on any per-symbol error, but inner `except Exception: pass` blocks at lines 254–255, 484, 501 swallow failures entirely with no log output.
- Safe modification: Replace silent `pass` blocks with `logger.warning`; add per-symbol failure counters to surface systematic data issues.
- Test coverage: No tests for the scan loop itself; `test_scalping_runner.py` covers the runner but not `pattern_alert`.

**`scheduler.py` mixes `asyncio` and `threading`:**
- Files: `engine/strategy/scheduler.py` (lines 73, 86–87, 126, 132, 144)
- Why fragile: An asyncio task is created (`loop.create_task`) inside a threading context; `asyncio.run_coroutine_threadsafe` is used from `control_bot.py` line 104. Mixing event loops and threads is error-prone across Python versions.
- Safe modification: Commit to one concurrency model; migrate scheduler to pure asyncio or pure threading with a dedicated thread pool.
- Test coverage: Not covered by any test.

**`engine/core/database.py` uses a module-level singleton `_engine` without thread safety:**
- Files: `engine/core/database.py` (lines 12–18)
- Why fragile: `get_engine()` creates the singleton engine only when `_engine is None`, but there is no lock guarding the check-then-set. Under concurrent first calls (e.g., from `ThreadPoolExecutor` in `scalping_runner`), two engines can be created.
- Safe modification: Add `threading.Lock` around the singleton creation; or use `functools.lru_cache` on `get_engine`.
- Test coverage: `test_trade_repository.py` tests the repository but does not test concurrent engine access.

**`_get_krw_rate()` returns a hardcoded fallback `1450.0` on any failure:**
- Files: `engine/strategy/pattern_alert.py` (line 83: `krw_fallback_rate: float = 1450.0`)
- Why fragile: Any network blip silently switches all KRW conversions to the fallback without alerting the operator; stale rate leads to incorrect chart annotations but no observable error.
- Safe modification: Log a `WARNING` on fallback; expose a metric or Discord alert when fallback rate is active.
- Test coverage: Not tested.

**`engine/analysis/exchange_dominance.py` uses hardcoded `usdkrw: float = 1350.0` default:**
- Files: `engine/analysis/exchange_dominance.py` (line 138)
- Why fragile: Default parameter is a stale FX rate embedded in source code. This default is used whenever the caller does not supply a live rate, silently producing incorrect kimchi-premium calculations.
- Safe modification: Remove the default value; force callers to provide a live-fetched rate or raise `ValueError`.
- Test coverage: Not tested.

---

## Scaling Limits

**SQLite as the trade database:**
- Current capacity: Suitable for single-process, low-frequency trading (hundreds of trades/day).
- Limit: SQLite write locks the entire database file; under `ThreadPoolExecutor`-driven multi-symbol scalping, concurrent writes will serialise or raise `OperationalError: database is locked`.
- Scaling path: Migrate to PostgreSQL via the same SQLAlchemy interface; update `db_url` default in `engine/core/database.py`.

**Upbit OHLCV cache `ThreadPoolExecutor(max_workers=5)` hardcoded:**
- Current capacity: 5 parallel Upbit REST calls.
- Limit: Upbit rate limit is 8 req/s; with 20 symbols × 5 timeframes = 100 requests per scan cycle, the pool creates a burst exceeding the rate limit at low intervals.
- Scaling path: Implement token-bucket rate limiter shared across all workers; expose `max_workers` as a config parameter.

---

## Dependencies at Risk

**`pyupbit` (no version pin observed in imports, unofficial SDK):**
- Risk: `pyupbit` is an unofficial community library with infrequent maintenance; API breakage is common after Upbit endpoint changes.
- Impact: `engine/execution/upbit_broker.py` and `engine/data/provider_upbit.py` would break silently if Upbit changes their REST schema.
- Migration plan: Abstract behind `BaseBroker` / `ProviderBase` interfaces already in place; swap implementation without touching callers.

**`ccxt` — version not pinned in visible dependency spec:**
- Risk: `ccxt` releases frequently and has breaking changes in exchange-specific parameters.
- Impact: `engine/execution/binance_broker.py` calls `enable_demo_trading`, `set_margin_mode`, `fetch_positions` — all ccxt-version-sensitive methods.
- Migration plan: Pin `ccxt>=4.x,<5` in `pyproject.toml`; add integration test against testnet on each ccxt update.

---

## Missing Critical Features

**No retry logic on Discord webhook sends:**
- Problem: `engine/notifications/alert_discord.py` sends Discord webhooks with no retry on HTTP 429 (rate limited) or transient errors. Any alert sent during Discord downtime is permanently lost.
- Blocks: Reliable alerting in production.

**No position reconciliation on ScalpingRunner restart:**
- Problem: `engine/execution/scalping_runner.py` initialises `self._positions` as an empty dict at startup. If the process restarts mid-trade, open positions on Binance are unknown to the runner, which may open duplicate positions.
- Blocks: Safe production deployment with auto-restart.

**Unrealized PnL not tracked for futures:**
- Problem: `BinanceBroker._fetch_raw_balance` returns `unrealized_pnl: 0.0` always (see Known Bugs). No alternative path fetches open position PnL.
- Blocks: Accurate risk management decisions in `RiskManager`.

---

## Test Coverage Gaps

**`engine/strategy/pattern_alert.py` — scan loop not tested:**
- What's not tested: `_scan_loop`, `start`, `stop`, `_load_sent_state`, `_save_sent_state`, `_send_alert` functions.
- Files: `engine/strategy/pattern_alert.py`
- Risk: Silent failures in the main alert loop could go undetected for hours.
- Priority: High

**`engine/strategy/scheduler.py` — no tests:**
- What's not tested: The entire asyncio scheduler lifecycle; `_bot_loop`, `start_scheduler`, `stop_scheduler`.
- Files: `engine/strategy/scheduler.py`
- Risk: Scheduler could silently stop running after an exception without any test catching it.
- Priority: High

**`engine/execution/binance_broker.py` — live exchange path not tested:**
- What's not tested: `_place_order`, `set_leverage`, `set_margin_mode`, `_fetch_raw_positions` (futures path), `_fetch_raw_balance` (futures).
- Files: `engine/execution/binance_broker.py`, `tests/test_binance_broker.py`
- Risk: Bugs in order placement or position parsing only surface in live/testnet trading.
- Priority: High

**`engine/analysis/` — minimal test coverage:**
- What's not tested: `crypto_regime.py`, `exchange_dominance.py`, `sector_regime.py`, `confluence.py` (only `test_confluence.py` exists but covers basic cases).
- Files: `engine/analysis/`
- Risk: Regime filter decisions are untested; incorrect regime classification could block or allow trades incorrectly.
- Priority: Medium

**Analysis scripts (`spike_precursor_analysis.py`, `spike_leadlag_analysis.py`) use `print()` instead of logging:**
- What's not tested: Output correctness is untestable because results go to stdout without structured return values.
- Files: `engine/strategy/spike_precursor_analysis.py`, `engine/strategy/spike_leadlag_analysis.py`
- Risk: Analysis scripts cannot be unit-tested or integrated into CI pipelines.
- Priority: Low

---

*Concerns audit: 2026-03-11*

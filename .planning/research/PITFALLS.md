# Pitfalls Research

**Domain:** Automated trading pipeline — strategy discovery, backtesting, paper trading, live deployment
**Researched:** 2026-03-11
**Confidence:** HIGH (backtesting/overfitting domain well-documented; monitoring patterns verified via multiple sources)

---

## Critical Pitfalls

### Pitfall 1: Single-Period Optimization Picked as Best Strategy

**What goes wrong:**
`GridOptimizer` and `ParallelOptimizer` both sort by Sharpe ratio over a single date range and return the top result. That top result is curve-fitted to that window. When deployed, performance reverts to mean or worse. The strategy "worked" in backtest but never had a statistical edge — it just got lucky on that slice of data.

**Why it happens:**
The current optimizer tests all combinations on the same data used to select the winner. With a parameter grid of N combinations, you are essentially running N experiments and cherry-picking the best one. Multiple-comparisons bias guarantees the winner looks better than it actually is.

**How to avoid:**
Implement walk-forward validation as a mandatory gate before any strategy advances. Split data into rolling windows: optimize on in-sample, measure on out-of-sample, advance the window, repeat. A strategy passes only if out-of-sample Sharpe is consistently above a minimum threshold (e.g. > 0.5) across at least 3 independent windows. Never select a winner based on in-sample results alone.

Minimum data requirements:
- 1m/5m strategies: 6+ months of tick data across multiple volatility regimes
- 1h/4h strategies: 2+ years
- 1d strategies: 4+ years including at least one major crash

**Warning signs:**
- Optimizer top result has Sharpe > 3.0 — near-certain overfitting
- Profit factor > 3.0 on in-sample — curve-fitted
- Parameter sensitivity: changing the winning param by ±1 step causes >30% Sharpe drop
- Strategy trade count < 30 in backtest period — insufficient sample

**Phase to address:** Strategy discovery / parameter optimization phase. Walk-forward must be built into the optimizer before the discovery engine is considered complete.

---

### Pitfall 2: Lookahead Bias in Signal Generation

**What goes wrong:**
A signal at bar N uses data from bar N+1 or later (e.g. close price of the signal bar is used as the fill price). The backtest shows perfect entries at exact highs/lows. In live trading, signals arrive after bar close and fill at next bar's open — a gap that compounds to significant underperformance.

**Why it happens:**
In the current `BacktestRunner._simulate()`, entry price is `close` at the signal bar (`signal == 1`). This means the strategy "buys at the close" of the bar that generated the signal. In reality, the signal is computed after that close is known, and the first tradeable moment is the next bar's open. For scalping strategies on 1m bars, this gap can be 0.1–0.5% per trade.

**How to avoid:**
Use next-bar-open as the fill price for all entries and exits, not the signal bar's close. Add a `fill_price_model` parameter to `BacktestRunner` with options: `close` (current, unrealistic), `next_open` (realistic minimum), `next_open_with_slippage` (production-ready). Default to `next_open_with_slippage` for all new backtests.

**Warning signs:**
- Live paper trading win rate is 10–20% lower than backtest win rate on identical logic
- Entry prices in live trading consistently worse than backtest entry prices
- Scalping strategies show dramatically lower live performance than 1h+ strategies

**Phase to address:** Backtesting enhancement phase. Fix fill price model before running any optimizer sweeps over the new indicator combinations.

---

### Pitfall 3: Slippage and Fees Modeled as Zero or Fixed Constant

**What goes wrong:**
The current `BacktestRunner._simulate()` applies no fees and no slippage. A strategy showing 20% annual return with zero costs may show 2% or negative after realistic costs are applied. This is especially destructive for scalping strategies with high trade frequency.

**Why it happens:**
Fixed-rate slippage models (e.g. "0.1% per trade") are better than zero but still wrong. Real slippage is:
- Volume-dependent: large orders in thin markets move price significantly
- Volatility-dependent: during fast moves, fills worsen dramatically
- Time-dependent: 1m scalping at 2 AM UTC has worse liquidity than 2 PM UTC

For crypto scalping: top-10 coins at peak hours = 0.05–0.1% slippage. Outside top-100 = 0.5–2%. Binance taker fee = 0.04–0.10% per leg. A 1m scalping strategy with 100 round-trips/month and 0.1% total cost per round-trip burns 10%/month in costs alone.

**How to avoid:**
Build a `SlippageModel` interface with three implementations:
1. `ZeroSlippage` — development only, never for strategy selection
2. `FixedBpsSlippage(bps=10)` — fast approximation
3. `VolumeAdjustedSlippage(base_bps, volume_fraction)` — production: slippage scales with order size / average bar volume

Always run final strategy evaluation with `VolumeAdjustedSlippage` + full taker fees. If a strategy does not survive 2x the expected slippage, reject it — it has no margin of safety.

**Warning signs:**
- Backtest trade count > 50/month on sub-hourly timeframes with no cost modeling
- Strategy passes backtest but paper trading shows immediate negative drift from day 1
- Profit factor in live trades is consistently 20–40% below backtest profit factor

**Phase to address:** Backtesting enhancement phase, before paper trading validation begins.

---

### Pitfall 4: No Out-of-Sample Holdout — Data Contamination

**What goes wrong:**
The entire historical dataset is used for strategy discovery, parameter tuning, and final validation. There is no data that the strategy has never "seen." When the strategy is deployed, the first true out-of-sample period is live trading with real money.

**Why it happens:**
It is tempting to use all available data to maximize sample size during development. This is correct reasoning for a single-pass analysis but wrong when the same data is used across multiple iterations of strategy selection.

**How to avoid:**
Reserve the most recent 20–30% of historical data as a permanently sealed holdout set. This data is touched exactly once: the final pre-deployment validation check. Do not use it during indicator sweep, parameter optimization, or walk-forward development. Automate enforcement: the data pipeline should refuse to return holdout-period data when called from the optimizer.

For the current project: if you have 2 years of 1h data, use 2023–2024 for discovery/optimization, reserve 2025–present as holdout. Evaluate every strategy candidate on holdout before promotion to paper trading.

**Warning signs:**
- Optimization loop has been run more than 5 times on the same dataset without a holdout split
- No documented "data you've never looked at" in the research pipeline
- Walk-forward OOS Sharpe > in-sample Sharpe — suspicious, suggests contamination

**Phase to address:** Strategy discovery infrastructure phase. Build holdout enforcement into the data pipeline before running any sweeps.

---

### Pitfall 5: Strategy Correlation Ignored in Portfolio Construction

**What goes wrong:**
Multiple strategies are deployed simultaneously, each passing individual validation. During normal market conditions they appear uncorrelated. During a crash or high-volatility regime, all strategies simultaneously generate stop-loss exits, resulting in concentrated drawdown that exceeds the sum of individual strategy drawdown limits.

**Why it happens:**
Strategy correlations are regime-dependent. Two momentum strategies on BTC/USDT and ETH/USDT show low correlation in trending markets but near-perfect correlation during flash crashes. The `RiskManager` in the current codebase manages per-symbol and total position count, but does not measure cross-strategy P&L correlation.

**How to avoid:**
Before promoting any combination of strategies to live portfolio:
1. Run all strategies simultaneously on the same historical period
2. Compute rolling 30-day correlation matrix of daily P&L
3. Reject any strategy pair with correlation > 0.7 in stress periods (high-vol regimes)
4. Enforce portfolio-level drawdown limit independent of per-strategy limits
5. Use conservative correlation estimates: if 5-year average is 0.3, budget for 0.6 in risk calculations

**Warning signs:**
- Multiple strategies share the same underlying indicators (e.g. two EMA-crossover variants)
- All deployed strategies are long-only crypto — they will all lose simultaneously in a crash
- Total portfolio drawdown in a bad week exceeds 2x the worst single-strategy drawdown

**Phase to address:** Portfolio risk management phase. Must be evaluated before any multi-strategy live deployment.

---

### Pitfall 6: Paper Trading Duration Too Short

**What goes wrong:**
A strategy is validated in paper trading for 1–2 weeks and promoted to live trading. The paper trading period happened to coincide with a trending, low-volatility market. The strategy immediately underperforms in live trading when market regime changes.

**Why it happens:**
1–2 weeks is insufficient to observe the full range of market conditions. Crypto markets cycle through distinct regimes (trending bull, trending bear, sideways chop, high-volatility crash) on timescales of weeks to months.

**How to avoid:**
Minimum paper trading duration before live promotion:
- 1m/5m scalping: 4 weeks minimum, must include at least one high-volatility event
- 15m/1h: 6 weeks minimum
- 4h/1d swing: 3 months minimum

Automated promotion gate: paper trading advancement to live requires:
- Minimum trade count: 30+ trades
- Live Sharpe (annualized from paper period) > 0.5
- Max drawdown in paper period < 1.5x backtest max drawdown
- Win rate within 15% of backtest win rate

**Warning signs:**
- Promoting after fewer than 20 live trades
- Paper trading only during a bull run
- No formal promotion criteria — subjective "looks good" assessment

**Phase to address:** Paper trading validation phase. Build the promotion gate as code, not a manual checklist.

---

### Pitfall 7: Strategy Degradation Goes Undetected Until Major Loss

**What goes wrong:**
A once-profitable strategy gradually stops working as market microstructure changes. Without monitoring, the system keeps trading a dead strategy for weeks or months, accumulating losses. By the time the loss is large enough to notice manually, significant capital has been destroyed.

**Why it happens:**
Market regimes change. Edge that existed in 2024 (e.g. BB squeeze on BTC 1h) may not exist in 2026 as liquidity providers adapt. Without automated degradation detection, the only signal is a large drawdown — which arrives late.

**How to avoid:**
Implement a rolling performance monitor that computes metrics over a sliding 20-trade window:
- Rolling Sharpe (annualized) vs. historical baseline
- Rolling win rate vs. historical baseline
- Rolling profit factor vs. historical baseline
- Consecutive loss counter

Alert thresholds (Discord notification):
- WARNING: rolling win rate drops > 15% below baseline for 2+ consecutive weeks
- WARNING: rolling Sharpe drops below 0 for rolling 20-trade window
- CRITICAL: consecutive losses >= `max_consecutive_sl` in `RiskConfig` — existing logic, keep it
- AUTO-PAUSE: rolling 30-trade Sharpe < -0.5 (strategy is actively losing)

Never auto-replace. Only auto-pause + alert. Human decides on replacement.

**Warning signs:**
- No degradation monitoring exists — everything is a warning sign
- Alerts only on large single-trade losses, not on gradual performance drift
- Weekly P&L review is the only monitoring mechanism

**Phase to address:** Performance monitoring system phase. Must be live before any strategy is promoted to live trading.

---

### Pitfall 8: Indicator Sweep Generates Spurious Discoveries (Multiple Comparisons)

**What goes wrong:**
An automated indicator sweep tests thousands of indicator combinations across 50+ symbols and 5 timeframes. With 10,000 combinations tested at p < 0.05 significance, approximately 500 will appear "significant" by random chance alone. These get promoted as "discovered strategies" and fail in paper trading.

**Why it happens:**
The current `ParallelOptimizer` runs grid search and sorts by Sharpe. There is no statistical correction for the number of comparisons tested. The more combinations tested, the more false positives are guaranteed.

**How to avoid:**
Apply multiple-comparisons correction to the discovery pipeline:
1. Require minimum Sharpe > 1.0 on in-sample (not just "top of list")
2. Require the strategy to rank in top 10% across at least 3 different historical windows (not just one)
3. Apply Bonferroni correction conceptually: if testing 1000 combinations, your significance threshold is 100x stricter
4. Require parameter robustness: ±20% change in each parameter should not drop Sharpe by more than 30%
5. Require cross-market validation: strategy must work on at least 2 uncorrelated symbols

**Warning signs:**
- Sweep generates 50+ "promising" strategies — too many signals means no signal
- Top strategy has drastically different parameters from 2nd-place strategy — no robustness
- Discovery pipeline has no minimum Sharpe floor — all results are "valid"

**Phase to address:** Strategy discovery engine phase. Build these filters into the sweep output ranking before any sweep results are forwarded to paper trading.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use close price as fill price in backtest | Simpler code, runs faster | Systematic overestimation of strategy edge; misleads all downstream decisions | Never — always use next-open |
| Single in-sample optimization, no walkforward | Faster development, easier to show "results" | All selected strategies are curve-fitted; paper trading failure rate high | Never for production strategy selection |
| Zero slippage / zero fees in optimizer | Faster sweep, cleaner metrics | Strategies with thin edge eliminated by real costs; high-frequency strategies massively overestimated | Only for initial screening with explicit labeling |
| Skip holdout reservation | Use more data for training | First true OOS test is live trading with real money | Never |
| Deploy strategy immediately after backtest without paper trading | Faster time-to-live | Unknown divergence between backtest and live; first real data on strategy viability is a loss | Never for strategies above minimum position size |
| Same dataset for discovery and validation | Simpler pipeline | All "validated" strategies are actually in-sample; no real validation exists | Never |
| Monitor only per-trade P&L, not rolling metrics | Less monitoring infrastructure | Degradation detected only after major drawdown, not early enough to act | Never in production |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Binance API order fills | Assuming limit orders fill at limit price | Limit orders may fill at worse price (price improvement not guaranteed on Binance) or not fill at all; track actual fill price from execution report |
| ccxt OHLCV data | Treating OHLCV close as "tradeable price at that moment" | OHLCV close is the last trade in that candle; first tradeable price is next candle's open; add one-bar lag to all entry/exit logic |
| ccxt multi-exchange | Using same symbol format across exchanges | Binance uses `BTC/USDT`, Upbit uses `KRW-BTC`; normalize to internal format at ingestion, denormalize at execution |
| SQLite concurrent writes | Multiple strategy threads writing trade records simultaneously | SQLite WAL mode or use a write queue; current SQLite + Repository pattern is fine for single-process, breaks with ProcessPoolExecutor workers |
| TA-Lib indicator warm-up | Running indicators on full data without checking NaN prefix | TA-Lib indicators require `period - 1` warm-up bars; first N rows are NaN; never use signal from warm-up period; assert no NaN in signal generation before backtest |
| Discord webhook rate limits | Sending one webhook per trade in high-frequency mode | Batch alerts: collect events in a queue, flush every 5 seconds with combined message; Binance scalping can generate 10+ signals/minute |
| Binance WebSocket reconnect | Assuming WebSocket connection is always live | Add explicit heartbeat check + auto-reconnect; binance_ws.py must handle silent disconnects that don't raise exceptions |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Grid search combinatorial explosion | 10 indicators × 10 params each = 10^10 combinations; sweep never completes | Use staged search: coarse grid first (5 values per param), then fine-tune top 10% candidates | At ~1000 combinations with slow backtests; at ~100k combinations with fast backtests |
| Loading all OHLCV data into memory per optimization worker | ProcessPoolExecutor spawns N workers, each loads full dataset; 8 workers × 500MB data = 4GB RAM | Cache OHLCV data on disk, each worker reads from shared cache; or pre-load once and pass slices | Breaks at 4+ workers with 1+ year of 1m data |
| Recomputing all indicators for every parameter combination | CPU-bound; 1000 combinations × full TA-Lib recalculation = minutes per symbol | Separate data fetch + indicator compute from signal generation; cache indicator outputs for fixed params | Noticeable at 100+ combinations |
| SQLite write contention in parallel backtest | Workers silently fail to write trade records; results incomplete | Use file-based results (pickle/JSON per worker), merge after all complete | Breaks immediately with ProcessPoolExecutor |
| Monitoring dashboard polling every second | 10 strategies × 10 symbols × 1-second poll = 100 DB queries/second | Push-based updates: write to state on trade events, dashboard reads on page load or 10-second interval | Breaks under any real load |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| API keys in config files committed to git | Exchange account compromise; entire capital at risk | Store in environment variables or system keyring; add `config/secrets*` to `.gitignore`; audit existing `config/discord.json` pattern |
| No position size cap in automated mode | Single runaway signal places 100% of capital in one position | Hard-cap: `max_position_size_pct` in `RiskConfig`; enforce at broker level, not just strategy level |
| Paper trading broker silently falls back to live broker on error | Paper trades execute as real trades | Fail-closed: if paper broker initialization fails, raise exception; never fall back to live |
| No circuit breaker on API error retry loop | Exchange API returns errors → bot retries indefinitely → burns through rate limits → account temporarily banned | Exponential backoff with max retries (3); after max retries, pause strategy and alert; never retry order placement without human review |
| Unencrypted trade history in SQLite | Local file contains full trading history, entry/exit prices, P&L | Acceptable for personal use; if server is shared or cloud-hosted, encrypt at rest or use PostgreSQL with row-level security |

---

## "Looks Done But Isn't" Checklist

- [ ] **Walk-forward optimizer:** The `ParallelOptimizer` runs grid search — verify it also enforces OOS validation windows before returning "top strategies"
- [ ] **Slippage model:** `BacktestRunner._simulate()` uses close price with no fees — verify cost model is applied before any optimizer results are trusted
- [ ] **Fill price realism:** Entry at signal-bar close vs. next-bar open — verify fill price model is `next_open` or better before strategy selection
- [ ] **Holdout data:** Verify the most recent 20–30% of historical data is reserved and never touched by discovery/optimization code
- [ ] **Paper trading gate:** Verify promotion from paper → live requires meeting quantitative criteria (Sharpe, trade count, drawdown), not just "looks good"
- [ ] **Strategy correlation check:** Verify no two simultaneously deployed strategies share correlation > 0.7 in stress-period P&L
- [ ] **Degradation monitoring:** Verify rolling metrics (20-trade window Sharpe, win rate) are computed and alerting in production, not just total P&L
- [ ] **TA-Lib NaN warm-up:** Verify signal generation asserts no NaN values in output before backtest simulation begins
- [ ] **Discord rate limiting:** Verify alert batching is implemented; single-trade-per-message will hit rate limits on 1m scalping
- [ ] **Binance WebSocket reconnect:** Verify `binance_ws.py` handles silent disconnects with heartbeat monitoring

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Deployed curve-fitted strategy, now losing | HIGH | Immediately pause strategy; do not average down or increase size; re-run discovery with proper walk-forward; minimum 4-week paper re-validation before any re-deployment |
| Fill price bug discovered after 3 months of live trading | MEDIUM | Audit all historical backtest results with corrected fill model; strategies that no longer pass must be paused; accept that live performance was the true ground truth |
| No slippage modeling — live results diverge | MEDIUM | Measure actual average slippage from live fills vs. fill price model; calibrate `VolumeAdjustedSlippage` to match observed data; re-rank all optimizer results with corrected model |
| Correlated strategies all hit stop-loss simultaneously | HIGH | Halt all automated trading; assess portfolio-level damage; do not re-deploy multiple strategies until correlation matrix is built and strategy set is re-selected with correlation constraint |
| Strategy degraded undetected for 6 weeks | MEDIUM | Reconstruct rolling metrics retroactively from trade DB to find degradation onset; use onset date for regime analysis to understand what changed; build monitoring before re-deployment |
| Paper trading holdout contamination discovered | HIGH | All strategies "validated" on contaminated data must be re-validated from scratch on fresh holdout; delay is mandatory — do not deploy without clean validation |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Single-period curve fitting | Strategy discovery / parameter optimization | Walk-forward OOS Sharpe reported alongside in-sample; top strategy must beat OOS threshold |
| Lookahead bias (close as fill) | Backtesting enhancement | Unit test: strategy buying at bar N must fill at bar N+1 open in simulation |
| Zero slippage / fees | Backtesting enhancement | Integration test: known strategy with 0.1% edge per trade shows near-zero return with 0.05% fee + 0.05% slippage |
| No holdout data | Strategy discovery infrastructure | Code review: data pipeline must reject requests for holdout-period data from optimizer module |
| Strategy correlation risk | Portfolio risk management | Correlation matrix computed and logged before any multi-strategy live deployment |
| Paper trading too short | Paper trading validation | Automated gate: promotion blocked until trade count ≥ 30 AND duration ≥ minimum threshold |
| Degradation undetected | Performance monitoring system | Alert fires in test environment when synthetic degraded-strategy data is fed to monitor |
| Multiple comparisons in sweep | Strategy discovery engine | Discovery pipeline only forwards strategies meeting Sharpe > 1.0 AND parameter robustness check |
| Slippage model not calibrated | Post-paper-trading, pre-live | Measured slippage from paper fills vs. model prediction < 20% error |

---

## Sources

- [Robustness Tests and Checks for Algorithmic Trading Strategies](https://www.buildalpha.com/robustness-testing-guide/) — walk-forward, parameter robustness
- [Common Pitfalls in Backtesting — Medium / Funny AI & Quant](https://medium.com/funny-ai-quant/ai-algorithmic-trading-common-pitfalls-in-backtesting-a-comprehensive-guide-for-algorithmic-ce97e1b1f7f7) — lookahead bias, survivorship bias
- [Walk-Forward Analysis — QuantInsti](https://blog.quantinsti.com/walk-forward-optimization-introduction/) — walk-forward methodology
- [Paper vs Live Slippage Analysis](https://markrbest.github.io/paper-vs-live/) — measured divergence between paper and live fills
- [Backtest Crypto Strategies with Real Market Data](https://www.coinapi.io/blog/backtest-crypto-strategies-with-real-market-data) — OHLCV limitations, order book modeling
- [Portfolio-Level Risk Constraints for Multi-Strategy Algorithms](https://breakingalpha.io/insights/portfolio-level-risk-constraints) — correlation surge in crisis, regime-conditional limits
- [How to Backtest a Crypto Bot: Realistic Fees, Slippage](https://paybis.com/blog/how-to-backtest-crypto-bot/) — realistic cost modeling for crypto
- [Interpretable Hypothesis-Driven Trading: Walk-Forward Validation](https://arxiv.org/html/2512.12924v1) — rigorous OOS testing framework
- [Backtesting Traps: Common Errors to Avoid](https://www.luxalgo.com/blog/backtesting-traps-common-errors-to-avoid/) — practical list of backtest errors
- [7 Risk Management Strategies for Algorithmic Trading](https://nurp.com/wisdom/7-risk-management-strategies-for-algorithmic-trading/) — monitoring and degradation detection

---

*Pitfalls research for: AutoTrader — Automated Trading Pipeline*
*Researched: 2026-03-11*

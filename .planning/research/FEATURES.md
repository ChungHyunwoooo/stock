# Feature Research

**Domain:** Automated trading pipeline (crypto/stock, multi-exchange, strategy discovery to live execution)
**Researched:** 2026-03-11
**Confidence:** MEDIUM-HIGH (stack is known; feature prioritization informed by industry research + codebase gap analysis)

---

## Existing System Baseline

The following are already built and NOT in scope for this research:

| Already Exists | Location |
|----------------|----------|
| OHLCV fetch + 2-layer cache | `engine/data/` |
| Indicator computation (TA-Lib + registry) | `engine/indicators/` |
| Chart/candle pattern recognition | `engine/patterns/`, `engine/strategy/` |
| Direction judgment (weighted confidence) | `engine/analysis/direction.py` |
| Strategy JSON schema (StrategyDefinition) | `engine/schema.py` |
| Scanner daemon (30s interval) | `engine/strategy/pattern_alert.py` |
| Paper/Binance/Upbit broker | `engine/execution/` |
| Discord webhook + slash-command bot | `engine/notifications/`, `engine/interfaces/discord/` |
| Backtest runner + Sharpe/MDD metrics | `engine/backtest/runner.py`, `metrics.py` |
| Grid optimizer (single symbol, single period) | `engine/backtest/optimizer.py` |
| Per-strategy risk (SL/TP/daily loss/consecutive SL) | `engine/strategy/risk_manager.py` |
| 17+ strategy JSON definitions | `strategies/` |
| REST API (FastAPI) | existing |
| SQLite trade DB + Repository | `engine/core/` |

Gap from baseline: the optimizer is single-symbol/single-period and optimizes only by Sharpe. No cross-period or cross-market stability check. No walk-forward. No automated strategy sweep. No portfolio-level risk. No lifecycle state machine beyond `StrategyStatus` enum. No performance degradation detection.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features the pipeline cannot ship without. Missing any of these makes the system functionally incomplete for its stated purpose.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Walk-forward validation (multi-period OOS test) | Grid-search on single period produces heavily overfit strategies; industry standard since at least 2020 | MEDIUM | Split data into IS/OOS windows, report OOS Sharpe + return; reject if IS/OOS gap > threshold. Extends existing `GridOptimizer`. |
| Realistic slippage + fee model in backtest | Current runner uses 100% fill at close price with no cost model; results are unreliable for live deployment decisions | MEDIUM | Model: fee = exchange taker rate × trade size; slippage = f(volume, spread); must be configurable per exchange. |
| Multi-market stability check in backtest | Single-symbol pass is insufficient; a strategy must hold across at least 2-3 uncorrelated symbols | MEDIUM | Re-run same strategy on a basket of symbols, require median Sharpe > threshold. Uses existing `BacktestRunner`. |
| Paper trading stage (live signals, no real orders) | Industry standard: backtest → paper → live. Skipping paper is a known cause of live losses from data-to-live slippage not captured in backtest | LOW | `PaperBroker` already exists. Need: persistent paper state, PnL tracking across sessions, promotion gate. |
| Paper → live promotion gate | Prevents untested strategies from entering live execution | LOW | Decision rule: paper_period ≥ N days, paper_win_rate ≥ X%, paper_sharpe ≥ Y. Currently manual. |
| Portfolio-level daily loss limit | Per-strategy limits exist. If 5 strategies all lose simultaneously, portfolio is unprotected | LOW | Aggregate daily PnL across all open strategies. Halt all new entries if total loss exceeds portfolio threshold. Extends existing `RiskManager`. |
| Strategy lifecycle state machine | `StrategyStatus` enum exists (draft/testing/active/archived) but transitions are manual; no enforcement | LOW | Define valid transitions: draft → testing → paper → active → archived. Gate each transition on criteria. |
| Performance degradation alert | Live strategy underperforming expectations must alert the operator; without this, losses compound undetected | MEDIUM | Rolling window metrics (last 20 trades): if win_rate or Sharpe falls > 30% from backtest baseline, send Discord alert. |
| Position + strategy status in Discord | Operators need current state without opening a dashboard; current bot lacks live position query | LOW | `/status` slash command: open positions, daily PnL, strategy states. `alert_positions.py` exists but is partial. |

### Differentiators (Competitive Advantage)

Features that advance beyond table stakes and align with the core value: "수익을 주는 자동화 봇 — 사람 개입 없이 돌아가되 제어권 유지."

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Automated indicator-combination sweep (strategy discovery) | Instead of hand-crafting every strategy, sweep indicator × parameter × timeframe space and surface candidates; expands the pipeline from human-authored to data-driven discovery | HIGH | Combinatorial explosion risk. Constrain search: fixed indicator pool (existing registry), 2-3 indicator combinations, pre-defined param ranges. Run via `parallel_optimizer.py`. Output: ranked candidate list, not auto-deployed strategy. |
| Reference-strategy importer (paper/community → JSON) | Known profitable patterns (e.g. Supertrend+RSI, VWAP deviation mean-reversion) can be encoded into `StrategyDefinition` systematically; creates a curated starting set for sweep fine-tuning | MEDIUM | Write a researcher workflow: find a strategy, define its indicators + conditions in JSON, backtest validate, add to `strategies/`. Not automation — structured process with templates. |
| Strategy correlation filter (portfolio construction) | Running 5 strategies that all trigger on the same BTC move provides no diversification. Block entry when new strategy correlates > 0.7 with any currently active strategy's recent signals | HIGH | Compute signal overlap using rolling window. Requires signal history store. |
| Adaptive position sizing (Kelly-fraction or ATR-based) | Fixed risk_per_trade_pct (currently 2%) ignores volatility. ATR-scaled sizing improves risk-adjusted returns in volatile regimes | MEDIUM | ATR already calculable via existing indicator registry. Kelly fraction needs win-rate + avg win/loss from trade DB. |
| Multi-timeframe confirmation gate | Entry signal from 1m/5m must be confirmed by 15m/1h direction judgment before execution; reduces false positives significantly | MEDIUM | `engine/analysis/mtf_confluence.py` exists. Wire it as an optional entry gate in the strategy evaluator. |
| Monitoring dashboard (web UI) | Centralised view: strategy lifecycle, open positions, equity curve, discovery queue, alerts. `streamlit_dashboard.py` exists but is a stub | HIGH | Extend existing Streamlit stub. Key panels: portfolio PnL, per-strategy performance, strategy state table, backtest history. |
| Walk-forward optimization with anchored IS window | Anchored (expanding) walk-forward is more robust than rolling for trending markets; finds params stable across regime changes | HIGH | CPCV (Combinatorial Purged Cross-Validation) is the 2025 state-of-the-art but complex; start with anchored walk-forward, flag CPCV as v2. |
| Backtest report persistence + comparison | Store each backtest result in DB with strategy ID, params, date run; enable before/after comparison when re-optimizing | LOW | Extend `BacktestResult.to_result_json()` to write to SQLite. Simple extension of existing DB pattern. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Automatic strategy replacement on degradation | Seems like full automation | Strategy retirement without human review can replace a temporarily struggling strategy with an overfit new one; 73% of fully-automated bots fail within 6 months per industry data | Alert + manual promotion. Operator decides replacement. |
| Real-time everything in dashboard | Low-latency feels professional | WebSocket feeds for every metric kill CPU on a single server. Most strategy metrics are meaningful only at bar-close (1m minimum) | Refresh on bar-close tick. Dashboard polls FastAPI every 30s. |
| HFT / sub-second execution | High potential returns | Requires co-location, custom networking, C++ execution layer; incompatible with Python stack | Stay at 1m minimum timeframe with Binance WebSocket (`engine/data/binance_ws.py`) |
| Fully automated indicator discovery (LLM/ML feature selection) | "AI finds the best indicators" | Without interpretability, the system becomes a black box; impossible to reason about why it's losing when it degrades | Constrained sweep over human-curated indicator pool with interpretable conditions |
| Social/copy trading | Community discovery of strategies | Security, regulatory, and liability surface; scope explosion | Internal strategy registry + reference importer is sufficient |
| Mobile app | Convenience | Discord + web dashboard covers all monitoring needs; mobile app is pure development cost for no trading value | Discord slash commands for alerts; Streamlit for web |
| Multi-broker arbitrage | Exploits price differences | Requires ultra-low latency, complex inventory management, and regulatory compliance in multiple jurisdictions | Multi-broker execution (ccxt) for redundancy only, not arbitrage |

---

## Feature Dependencies

```
[Walk-forward validation]
    └──requires──> [Realistic slippage/fee model]
    └──requires──> [Multi-market stability check]
                       └──requires──> [BacktestRunner (existing)]

[Paper trading stage]
    └──requires──> [PaperBroker (existing)]
    └──requires──> [Strategy lifecycle state machine]

[Paper → live promotion gate]
    └──requires──> [Paper trading stage]
    └──requires──> [Trade DB (existing)]

[Performance degradation alert]
    └──requires──> [Trade DB (existing)]
    └──requires──> [Discord webhook (existing)]
    └──enhances──> [Strategy lifecycle state machine]

[Portfolio-level daily loss limit]
    └──requires──> [Per-strategy RiskManager (existing)]
    └──enhances──> [Paper → live promotion gate]

[Strategy correlation filter]
    └──requires──> [Signal history store]
    └──requires──> [Trade DB (existing)]
    └──enhances──> [Portfolio-level daily loss limit]

[Adaptive position sizing]
    └──requires──> [ATR indicator (existing registry)]
    └──requires──> [Trade DB win/loss stats (existing)]
    └──enhances──> [Paper → live promotion gate]

[Automated indicator sweep]
    └──requires──> [Walk-forward validation]
    └──requires──> [Multi-market stability check]
    └──requires──> [parallel_optimizer.py (existing, partial)]

[Multi-timeframe confirmation gate]
    └──requires──> [mtf_confluence.py (existing)]
    └──enhances──> [Paper trading stage]

[Monitoring dashboard]
    └──requires──> [FastAPI REST (existing)]
    └──requires──> [Trade DB (existing)]
    └──enhances──> [Performance degradation alert]
    └──enhances──> [Strategy lifecycle state machine]

[Backtest report persistence]
    └──requires──> [Trade DB (existing)]
    └──enhances──> [Walk-forward validation]
    └──enhances──> [Monitoring dashboard]
```

### Dependency Notes

- **Walk-forward requires slippage model:** OOS results are meaningless without cost modeling; the cost model must exist first or walk-forward conclusions are false positives.
- **Automated sweep requires walk-forward:** Running sweep with only in-sample Sharpe produces 100% overfit candidates; sweep is only safe after OOS validation is in place.
- **Paper stage requires lifecycle state machine:** Without enforced state transitions, paper and live modes can coexist unsafely (both executing real positions).
- **Degradation alert requires trade DB:** Rolling-window metrics are computed from stored trade history; no DB = no detection.
- **Correlation filter requires signal history:** Needs recent signal vectors per strategy; this is new storage not in current DB schema.

---

## MVP Definition

### Launch With (v1) — "Pipeline is safe to run live"

These features make the pipeline trustworthy enough to run with real capital.

- [ ] **Realistic slippage + fee model** — without this, no backtest result is credible for live deployment
- [ ] **Walk-forward validation (multi-period OOS)** — prevents deploying overfit strategies
- [ ] **Multi-market stability check** — single-symbol pass is insufficient quality gate
- [ ] **Paper trading stage with persistent PnL** — mandatory staging before live; PaperBroker already exists, needs persistence
- [ ] **Paper → live promotion gate (rule-based)** — formalises the staging checkpoint
- [ ] **Portfolio-level daily loss limit** — closes the gap in existing per-strategy risk management
- [ ] **Strategy lifecycle state machine (enforced transitions)** — prevents draft strategies from entering live execution
- [ ] **Performance degradation alert** — operator control when live strategy underperforms

### Add After Validation (v1.x) — "Pipeline improves itself"

Add once the safe-to-run foundation is validated.

- [ ] **Backtest report persistence + comparison** — enables iterative re-optimization; low complexity, high value
- [ ] **Adaptive position sizing (ATR-based)** — improves risk-adjusted returns; trigger: 30+ live trades in DB
- [ ] **Multi-timeframe confirmation gate** — reduces false entries; `mtf_confluence.py` exists; trigger: paper win-rate below target
- [ ] **Reference-strategy importer workflow** — structured process to add curated strategies; trigger: discovery queue is exhausted
- [ ] **Monitoring dashboard (Streamlit extension)** — centralised view; trigger: operating more than 3 simultaneous strategies

### Future Consideration (v2+) — "Pipeline scales"

Defer until v1 is proven profitable.

- [ ] **Automated indicator-combination sweep** — high complexity, needs walk-forward + stability check in place first
- [ ] **Strategy correlation filter** — needs signal history schema and sufficient live strategy count (5+) to be meaningful
- [ ] **Walk-forward with anchored IS window / CPCV** — upgrade from basic OOS split; defer until basic walk-forward is running
- [ ] **ccxt multi-exchange expansion** — adds redundancy and opportunity; defer until single-exchange pipeline is stable

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Realistic slippage + fee model | HIGH | MEDIUM | P1 |
| Walk-forward validation | HIGH | MEDIUM | P1 |
| Multi-market stability check | HIGH | LOW | P1 |
| Paper trading stage (persistent) | HIGH | LOW | P1 |
| Paper → live promotion gate | HIGH | LOW | P1 |
| Portfolio-level daily loss limit | HIGH | LOW | P1 |
| Strategy lifecycle state machine | HIGH | LOW | P1 |
| Performance degradation alert | HIGH | MEDIUM | P1 |
| Backtest report persistence | MEDIUM | LOW | P2 |
| Adaptive position sizing | MEDIUM | MEDIUM | P2 |
| Multi-timeframe confirmation gate | MEDIUM | LOW | P2 |
| Reference-strategy importer workflow | MEDIUM | LOW | P2 |
| Monitoring dashboard (Streamlit) | MEDIUM | HIGH | P2 |
| Automated indicator sweep | HIGH | HIGH | P3 |
| Strategy correlation filter | MEDIUM | HIGH | P3 |
| CPCV walk-forward | MEDIUM | HIGH | P3 |
| ccxt multi-exchange expansion | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for safe live deployment
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

Context: this is a private system, not a product. "Competitors" are reference implementations used to calibrate feature completeness.

| Feature | QuantConnect / Lean | 3Commas | freqtrade | Our Approach |
|---------|---------------------|---------|-----------|--------------|
| Backtest OOS validation | Walk-forward built-in | None (in-sample only) | Walk-forward optional | Walk-forward as P1 requirement |
| Paper trading stage | Paper trading built-in | Paper trading built-in | Dry-run mode built-in | Extend existing PaperBroker with persistence |
| Portfolio risk | Portfolio-level limits | Per-bot stop-loss only | Global stop-loss | Portfolio daily loss limit + correlation filter (v2) |
| Strategy lifecycle | Draft/live/archived states | Start/stop only | None formal | Enforced state machine on StrategyStatus enum |
| Performance monitoring | Full equity dashboard | Basic PnL per bot | Telegram/Discord alerts | Discord alerts (v1) + Streamlit dashboard (v2) |
| Strategy discovery | Manual + community | Manual only | Hyperopt parameter search | Grid sweep (existing) → automated sweep (v3) |
| Slippage model | Realistic configurable model | Fixed fee only | Configurable fee + slippage | Configurable per-exchange model (P1) |

**Key gap vs freqtrade** (the closest open-source equivalent): freqtrade has dry-run, hyperopt, and configurable fees. Our system needs parity on these three before adding differentiating features.

---

## Sources

- [AI Trading Bot Risk Management: Complete 2025 Guide — 3commas.io](https://3commas.io/blog/ai-trading-bot-risk-management-guide-2025)
- [Backtest overfitting CPCV comparison — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)
- [Walk-Forward Optimization introduction — QuantInsti](https://blog.quantinsti.com/walk-forward-optimization-introduction/)
- [The Lifecycle of an Algorithmic Trading Bot — Medium](https://medium.com/ai-simplified-in-plain-english/the-lifecycle-of-an-algorithmic-trading-bot-from-optimization-to-autonomous-operation-3f9d5ceba12e)
- [Algorithmic Trading Monitoring and Management — ION Group](https://iongroup.com/blog/markets/algorithmic-trading-monitoring-and-management/)
- [Comprehensive 2025 Guide to Backtesting AI Crypto Trading Strategies — 3Commas](https://3commas.io/blog/comprehensive-2025-guide-to-backtesting-ai-trading)
- [Why Most Trading Bots Lose Money — ForTraders](https://www.fortraders.com/blog/trading-bots-lose-money)
- [QuantConnect open-source platform — quantconnect.com](https://www.quantconnect.com/)
- Codebase gap analysis: `engine/backtest/optimizer.py`, `engine/strategy/risk_manager.py`, `engine/schema.py`, `engine/backtest/runner.py`

---

*Feature research for: AutoTrader — Automated Trading Pipeline*
*Researched: 2026-03-11*

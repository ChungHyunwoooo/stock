# Stack Research

**Domain:** Automated trading pipeline — strategy discovery, advanced backtesting, paper trading, portfolio risk, monitoring dashboard
**Researched:** 2026-03-11
**Confidence:** MEDIUM-HIGH (versions verified via PyPI; some library-specific claims from WebSearch only)

---

## Context: What Already Exists

The existing stack (Python 3.12, ccxt 4.2+, TA-Lib, pandas-ta, SQLAlchemy/SQLite, FastAPI, Discord.py, bt, quantstats, Streamlit) is **kept as-is**. This document covers only **additive** libraries required for the new milestone capabilities.

---

## Recommended Stack — Additive Libraries

### Strategy Discovery: Parameter Optimization

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `optuna` | 4.7.0 | Bayesian hyperparameter search for indicator/param sweeps | Industry-standard TPE + CMA-ES samplers; define-by-run API fits naturally into existing backtest loop; pruners stop bad trials early saving CPU. Freqtrade uses it natively. |
| `joblib` | 1.4+ (stdlib-adjacent) | Parallel CPU execution of backtest sweep grid | Already a transitive dependency of scikit-learn; `Parallel(n_jobs=-1)` pattern is the standard for CPU-bound sweep parallelism without multiprocessing boilerplate. |
| `optuna-dashboard` | 0.17+ | Real-time browser UI for optimization runs | Zero-config companion to optuna; shows trial history, param importance, and pruning status during long sweeps. Optional but high value. |

**Why not ray[tune]:** Ray adds a distributed cluster abstraction that is overkill for a single Linux machine. Optuna + joblib covers the same local parallelism with zero infrastructure cost.

**Why not hyperopt:** Older API, less active maintenance. Optuna's define-by-run API is strictly more flexible and better documented as of 2025.

---

### Advanced Backtesting

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `vectorbt` | 0.28.4 | Vectorized multi-period stability testing + realistic slippage modeling | NumPy/Numba-accelerated; can run thousands of parameter configurations in seconds. Supports percentage-based slippage, fixed-fee models, and order-type simulation. Fills gap that `bt` leaves for bulk sweep validation. |

**Relationship to existing `bt`:** Keep `bt` for single-strategy narrative reporting and quantstats tearsheets. Use `vectorbt` for the sweep/stability testing layer where speed matters. They are complementary, not replacements.

**Note on vectorbt PRO:** The open-source `vectorbt` 0.28.4 (free, PyPI) is sufficient. PRO is invite-only and not publicly installable. The claim of "Binance fill accuracy within 0.3%" originates from a single WebSearch result and is LOW confidence — treat percentage slippage config as good-enough approximation and validate empirically.

**Why not backtrader:** Development stopped in 2018. Incompatible with Python 3.12+ without patching.

**Why not zipline:** Designed for Python 3.5-3.6 equity markets; installation in 3.12 requires forks and workarounds. Not worth the integration cost.

---

### Portfolio-Level Risk Management

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `riskfolio-lib` | 7.0+ | Strategy correlation analysis, capital allocation optimization, Kelly-criterion sizing | Built on CVXPY + pandas; supports Mean-Risk, HRP (Hierarchical Risk Parity), and Kelly portfolio optimization. Python 3.11/3.12/3.13 compatible. Directly addresses multi-strategy correlation and exposure management requirements. |
| `scikit-learn` | 1.5+ | Strategy return clustering (AgglomerativeClustering / correlation distance matrix) | Already likely a transitive dep; `AgglomerativeClustering` with correlation-based distance is the standard approach for grouping co-moving strategies before risk allocation. |

**Why riskfolio-lib over cvxpy directly:** Riskfolio-lib wraps CVXPY with domain-specific portfolio models (HRP, CVaR, Kelly) that would take significant effort to implement from scratch. The HRP algorithm specifically handles strategy correlation grouping — exactly what portfolio-level risk management requires.

**Why not PyPortfolioOpt:** Less maintained than riskfolio-lib as of 2025. Riskfolio-lib 7.x has more active development and broader optimization model coverage.

---

### Real-Time Data: WebSocket Streams

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `ccxt` (pro features) | 4.2+ (existing) | WebSocket order book and trade streams for paper trading | ccxt.pro WebSocket API is now bundled in the standard ccxt package (no separate install). Use `ccxt.pro` namespace with async/await. Provides `watchOrderBook`, `watchTrades`, `watchOHLCV` across Binance, Upbit, Bybit, OKX. |

**Action required:** Current codebase uses ccxt REST. Paper trading pipeline needs `asyncio` + `ccxt.pro` watch* methods. No new package install — architecture change only.

---

### Monitoring Dashboard

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `streamlit` | 1.55.0 | Real-time position/strategy performance/system status dashboard | Already present in codebase (optional import). Upgrade to 1.55.0. Use `st.rerun()` with auto-refresh for live updates. Sufficient for internal monitoring without introducing a separate frontend stack. |
| `plotly` | 5.x | Interactive charts inside Streamlit (PnL curves, drawdown, heatmaps) | Standard Streamlit chart companion. `st.plotly_chart` with `use_container_width=True`. Lighter than Bokeh, richer than Altair for trading-specific visuals. |

**Why not Grafana:** Requires a separate service + time-series DB (InfluxDB or Prometheus). Overkill for a single-user trading monitor where SQLite + Streamlit is already the pattern.

**Why not Dash (Plotly):** Requires defining callbacks and a separate app server. Streamlit's simpler execution model is faster to iterate on for this use case.

---

### Scheduler (Paper Trading Pipeline Orchestration)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `APScheduler` | 3.10+ | Scheduling paper trading cycles, performance checks, strategy sweep jobs | BackgroundScheduler runs inside the existing FastAPI/asyncio process without blocking. Supports cron, interval, and one-shot triggers. Persists job state across restarts (SQLAlchemy jobstore — already in stack). |

**Why not `schedule` library:** No persistence, no async support, no job store. Fine for prototypes; insufficient for a production pipeline that must survive restarts.

**Why not Celery:** Requires Redis/RabbitMQ broker. Distributed task queue is architecturally disproportionate to a single-machine bot.

---

## Supporting Libraries (Already in Stack — Upgrade Notes)

| Library | Current | Recommended | Note |
|---------|---------|-------------|------|
| `quantstats` | 0.0.62+ | 0.0.62+ (keep) | Already used for tearsheets. Do NOT add pyfolio — unmaintained, broken on pandas 2.x. |
| `pandas` | 2.2+ | 2.2+ (keep) | vectorbt 0.28.4 requires pandas 2.x — compatible. |
| `numpy` | 1.26+ | 1.26+ (keep) | vectorbt uses numpy/numba internally — compatible. |

---

## Installation

```bash
# Strategy discovery
pip install "optuna>=4.7.0" "optuna-dashboard>=0.17"

# Advanced backtesting
pip install "vectorbt>=0.28.4"

# Portfolio risk management
pip install "riskfolio-lib>=7.0" "scikit-learn>=1.5"

# Dashboard (upgrade existing)
pip install "streamlit>=1.55.0" "plotly>=5.0"

# Pipeline scheduling
pip install "APScheduler>=3.10"

# joblib is already installed as scikit-learn dependency — no explicit install needed
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| optuna | ray[tune] | Only if distributing sweeps across multiple machines |
| optuna | hyperopt | Legacy codebases already using hyperopt — not worth migrating from |
| vectorbt | backtesting.py | Single-strategy readable backtests (not sweep); lighter API |
| riskfolio-lib | PyPortfolioOpt | Simpler mean-variance only; no HRP or Kelly support |
| APScheduler | Celery | Multi-machine distributed task queues with Redis broker |
| Streamlit | Grafana | Time-series metrics at scale with multiple data sources |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `pyfolio` (original Quantopian) | Broken on pandas 2.x, unmaintained since 2020 | `quantstats` (already in stack) |
| `backtrader` | Development stopped 2018, Python 3.12 incompatible without patches | `vectorbt` for sweeps, `bt` for single-strategy |
| `zipline` / `zipline-reloaded` | Designed for Python 3.5-3.6, equity-only, hours-long for minute data | `vectorbt` |
| `ray[tune]` | Distributed cluster overhead for single-machine use | `optuna` + `joblib` |
| `celery` | Requires Redis/RabbitMQ broker, overkill for single process | `APScheduler` BackgroundScheduler |
| `dash` (Plotly) | Full React app + callback architecture for internal monitoring | `streamlit` |

---

## Version Compatibility Notes

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| vectorbt 0.28.4 | Python 3.10-3.13, pandas 2.x, numpy 1.26+ | Numba JIT compilation adds ~5s import time on first run; expected behavior |
| optuna 4.7.0 | Python 3.9-3.14 | Use `optuna.create_study(direction="maximize")` with Sharpe ratio objective |
| riskfolio-lib 7.0 | Python 3.11-3.13, cvxpy, pandas 2.x | CVXPY solver (default: CLARABEL) must be available; bundled in install |
| APScheduler 3.10 | Python 3.8+, SQLAlchemy 2.x | Use SQLAlchemyJobStore pointing at existing `tse.db` for persistence |
| streamlit 1.55.0 | Python 3.9+, plotly 5.x | `st.rerun()` replaces deprecated `st.experimental_rerun()` |

---

## Sources

- [optuna PyPI](https://pypi.org/project/optuna/) — version 4.7.0 confirmed, Python >=3.9 (HIGH confidence)
- [vectorbt PyPI](https://pypi.org/project/vectorbt/) — version 0.28.4 confirmed, Python >=3.10 (HIGH confidence)
- [Riskfolio-Lib PyPI](https://pypi.org/project/Riskfolio-Lib/) — version 7.0+ confirmed via WebSearch; GitHub releases page returned no results (MEDIUM confidence)
- [streamlit PyPI](https://pypi.org/project/streamlit/) — version 1.55.0 confirmed (HIGH confidence)
- [ccxt.pro WebSocket manual](https://github.com/ccxt/ccxt/wiki/ccxt.pro.manual) — bundled in ccxt, no separate install (HIGH confidence)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/) — 3.10+ confirmed; SQLAlchemy jobstore compatibility (HIGH confidence)
- [vectorbt vs backtrader comparison](https://greyhoundanalytics.com/blog/vectorbt-vs-backtrader/) — backtrader unmaintained since 2018 (MEDIUM confidence, multiple sources agree)
- [pyfolio alternatives analysis](https://tradingbrokers.com/pyfolio-alternatives/) — quantstats as recommended replacement (MEDIUM confidence)
- [Freqtrade hyperopt](https://www.freqtrade.io/en/stable/hyperopt/) — optuna integration in production trading system (HIGH confidence, official docs)
- [joblib parallel backtesting patterns](https://thepythonlab.medium.com/backtesting-and-optimizing-quant-trading-strategies-with-python-80cb94315588) — standard pattern confirmed (MEDIUM confidence, WebSearch)
- [Riskfolio-Lib docs](https://riskfolio-lib.readthedocs.io/) — Kelly + HRP optimization models (MEDIUM confidence)
- [scikit-learn clustering docs](https://scikit-learn.org/stable/modules/clustering.html) — AgglomerativeClustering for correlation-based grouping (HIGH confidence, official docs)

---

*Stack research for: Automated trading pipeline — strategy discovery and execution*
*Researched: 2026-03-11*

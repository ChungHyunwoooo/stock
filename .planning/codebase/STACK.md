# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python 3.12.3 - All engine, API, strategy, backtesting, and CLI code

**Secondary:**
- JSON - Configuration files (`config/discord.json`, `config/broker.json`, `config/alert_runtime.json`, `strategies/*/definition.json`)

## Runtime

**Environment:**
- CPython 3.12.3 (requires >=3.11 per `pyproject.toml`)
- Virtual environment: `.venv/` (standard `venv`)

**Package Manager:**
- pip / hatchling (build backend)
- Lockfile: Not present (no `requirements.lock` or `uv.lock`; only `pyproject.toml`)

## Frameworks

**Web API:**
- FastAPI 0.109+ — REST API server at `api/main.py`; routers under `api/routers/`
- Uvicorn 0.27+ (standard extras) — ASGI server for FastAPI

**Discord Bot:**
- discord.py 2.4+ — Slash command bot at `engine/interfaces/discord/control_bot.py`

**CLI:**
- Typer 0.9+ (with `all` extras for rich output) — CLI entry point at `engine/cli.py`, installed as `tse` script

**Dashboard:**
- Streamlit (optional, not in main deps) — PnL dashboard at `engine/interfaces/streamlit_dashboard.py`; guarded with `try/except ImportError`

**Testing:**
- pytest 8.0+ — Test runner; config in `pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`)
- pytest-asyncio 0.23+ — Async test support

**Build:**
- hatchling — Wheel build backend; packages `engine` and `api`

## Key Dependencies

**Critical (market data):**
- `ccxt` 4.2+ — Unified crypto exchange API; used for OHLCV fetch, order placement, balance/position queries across Binance (spot+futures via `binanceusdm`), Bybit, OKX, Upbit. See `engine/data/provider_crypto.py`, `engine/execution/binance_broker.py`
- `pyupbit` (not in pyproject.toml but imported) — Upbit REST + WebSocket; used in `engine/data/upbit_cache.py`, `engine/data/upbit_ws.py`, `engine/execution/upbit_broker.py`
- `finance-datareader` 0.9.66+ — KR/US stock OHLCV via `engine/data/provider_fdr.py`
- `yfinance` 0.2.36+ — Alternative stock data provider (declared in deps, not yet actively imported in engine)

**Technical Indicators:**
- `TA-Lib` 0.5.1+ — C-extension TA library; used broadly across `engine/indicators/price/`, `engine/indicators/momentum/`, `engine/indicators/volume/`, and many strategy files. Import alias: `talib` / `talib.abstract as ta`
- `pandas-ta` 0.3.14b1+ — Alternative TA library (declared; selective use)

**Backtesting & Analysis:**
- `bt` 1.1+ — Backtesting framework; `engine/backtest/`
- `quantstats` 0.0.62+ — Performance statistics and tear sheets

**Data Processing:**
- `pandas` 2.2+ — Core DataFrame; used everywhere
- `numpy` 1.26+ — Numerical arrays
- `pyarrow` 15.0+ — Parquet support for OHLCV cache persistence

**Persistence:**
- `sqlalchemy` 2.0.25+ — ORM for SQLite trade database; models at `engine/core/db_models.py`, session management at `engine/core/database.py`
- `pydantic` 2.6+ — Schema validation and domain models at `engine/core/models.py`, `engine/schema.py`

**Utilities:**
- `python-frontmatter` 1.1+ — Parsing strategy `research.md` files with YAML frontmatter
- `rich` 13.7+ — Terminal formatting for CLI output

**Dev:**
- `ruff` 0.2+ — Linter and formatter; config in `pyproject.toml` (`target-version = "py311"`, `line-length = 100`, rules E/F/I/N/W)
- `httpx` 0.27+ — HTTP client for API integration tests

## Configuration

**Environment:**
- `.env` file loaded by systemd `EnvironmentFile=` directive in service units
- Key env vars: `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`, `UPBIT_API_KEY`, `UPBIT_SECRET_KEY`
- Optional: `DISCORD_WEBHOOK_URL` (overrides config file webhook)
- Runtime config resolved via `engine/config_path.py`

**Application Config Files:**
- `config/discord.json` — Discord webhook URLs per timeframe + bot token
- `config/broker.json` — Exchange credentials (references env vars), risk params
- `config/alert_runtime.json` — Scanner symbols, timeframes, intervals, strategy dir
- `config/pattern_alert.json` — Pattern scanner state
- `config/exchange_symbol_cache/{exchange}.json` — Cached exchange symbol lists (12h TTL)
- `state/` — Runtime state files
- `strategies/` — Strategy registry (`registry.json`) and per-strategy definitions

**Build:**
- `pyproject.toml` — Single source of truth for dependencies, scripts, build, lint, and test config

## Platform Requirements

**Development:**
- Linux (systemd-based deployment confirmed)
- Python 3.11+ (3.12.3 in use)
- TA-Lib C library must be installed system-wide (C extension dependency)
- `.venv/` virtualenv at project root

**Production:**
- Linux systemd services: `deploy/pattern-alert.service`, `deploy/scalping-runner.service`
- Run as user `hwchung`; working directory `/home/hwchung/workspace/01_Project/02_stock`
- SQLite database file: `tse.db` at project root
- No containerization detected

---

*Stack analysis: 2026-03-11*

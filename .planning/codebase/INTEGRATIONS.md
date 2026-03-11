# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**Crypto Exchanges (via ccxt):**
- Binance Spot — OHLCV data fetch, market order/limit order execution, balance queries
  - SDK/Client: `ccxt.binance` (spot), `ccxt.binanceusdm` (futures)
  - Auth: `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` (env vars)
  - Testnet support: `exchange.enable_demo_trading(True)`
  - Files: `engine/execution/binance_broker.py`, `engine/data/provider_crypto.py`
- Binance Futures (USDM) — Futures order placement, position fetch, leverage/margin mode setting
  - SDK/Client: `ccxt.binanceusdm`
  - Auth: same as Binance Spot keys
  - Files: `engine/execution/binance_broker.py`, `engine/execution/scalping_runner.py`
- Upbit — KRW crypto market data and order execution
  - SDK/Client: `pyupbit` (REST + WebSocket)
  - Auth: `UPBIT_API_KEY`, `UPBIT_SECRET_KEY` (env vars)
  - Files: `engine/execution/upbit_broker.py`, `engine/data/provider_upbit.py`, `engine/data/upbit_cache.py`
- Bybit, OKX — Symbol list caching and OHLCV data (read-only, no trading)
  - SDK/Client: `ccxt.bybit`, `ccxt.okx`
  - Auth: None (public endpoints only)
  - Files: `engine/data/provider_crypto.py`

**Stock Market Data:**
- FinanceDataReader — Korean (KRX) and US (NYSE/NASDAQ) stock OHLCV
  - SDK/Client: `FinanceDataReader` (`finance-datareader` package)
  - Auth: None (public)
  - Files: `engine/data/provider_fdr.py`
- yFinance — US stock/ETF data (declared dependency; alternate provider)
  - SDK/Client: `yfinance`
  - Auth: None (public)

## Data Storage

**Databases:**
- SQLite — Primary trade persistence database
  - Connection: `sqlite:///tse.db` (project root, default in `engine/core/database.py`)
  - Client: SQLAlchemy 2.0 ORM with `create_engine` / `sessionmaker`
  - Models: `engine/core/db_models.py`
  - Repository: `engine/core/repository.py`
  - Init: `engine/core/database.py` (`init_db()`)

**File Storage:**
- Local filesystem only
  - OHLCV cache: Parquet files via `pyarrow` (location managed by `engine/data/ohlcv_cache.py`)
  - Upbit OHLCV cache: `engine/data/upbit_cache.py`
  - Exchange symbol cache: `config/exchange_symbol_cache/{exchange}.json` (12h TTL)
  - Strategy definitions: `strategies/{id}/definition.json` + `research.md`
  - Knowledge base: JSON store at `engine/core/knowledge_store.py`, `engine/core/json_store.py`

**Caching:**
- In-memory: `lru_cache` for ccxt exchange instances (`engine/data/provider_crypto.py`)
- On-disk Parquet: OHLCV two-layer cache (raw + processed)
- On-disk JSON: Exchange symbol lists (`config/exchange_symbol_cache/`)

## Authentication & Identity

**Auth Provider:**
- Custom (no auth middleware detected in FastAPI app)
  - `api/main.py` uses `CORSMiddleware` with `allow_origins=["*"]` — no authentication enforced
  - Discord bot token via `config/discord.json` (`bot_token` field)
  - Exchange API keys via env vars (`.env` file, loaded by systemd `EnvironmentFile=`)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, or similar SDK detected)

**Logs:**
- Python stdlib `logging` module used throughout; structured as `logging.getLogger(__name__)`
- systemd journal: `StandardOutput=journal`, `StandardError=journal` in service units
- Identifier labels: `SyslogIdentifier=pattern-alert`, `SyslogIdentifier=scalping-runner`

## CI/CD & Deployment

**Hosting:**
- Local Linux server; user `hwchung`
- Working directory: `/home/hwchung/workspace/01_Project/02_stock`
- Virtualenv: `.venv/` (path hardcoded in service `ExecStart`)

**Process Management:**
- systemd services (two units in `deploy/`):
  - `pattern-alert.service` — Runs `python -m engine.strategy.pattern_alert` (pattern scanner daemon)
  - `scalping-runner.service` — Runs `python -m engine.execution.scalping_runner` with symbol list and duration args
- Both: `Restart=on-failure`, `RestartSec=30`, `After=network-online.target`

**CI Pipeline:**
- None detected (no GitHub Actions, GitLab CI, or similar config files)

## Webhooks & Callbacks

**Outgoing (Discord Webhooks):**
- `DiscordWebhookNotifier` sends signals, pending orders, and execution records to Discord channels
  - Implementation: `engine/notifications/discord_webhook.py`
  - Transport: `urllib.request` (stdlib HTTP, no `requests`/`httpx` dependency)
  - Supports multipart/form-data for chart image (`chart.png`) attachments
  - URL resolution: env var `DISCORD_WEBHOOK_URL` > `config/discord.json` webhooks per timeframe key (`tf_5m`, `tf_15m`, etc.) > fallback `webhook_url`
  - Configured channels: `scalping`, `swing`, `tf_4h`, `tf_1h`, `tf_30m`, `tf_15m`, `tf_5m`, `analysis_pattern`

**Incoming (Discord Bot Slash Commands):**
- Discord bot via `discord.py` at `engine/interfaces/discord/control_bot.py`
- Slash commands implemented in `engine/interfaces/discord/commands/` (analysis, pattern, scanner modules)
- Bot started automatically on FastAPI startup via `engine/interfaces/discord/__init__.py:run_bot_background()`
- Bot token: `config/discord.json` → `bot_token`

**Incoming (REST API):**
- FastAPI server at `api/main.py`; prefix `/api`
- Routers: `alerts`, `backtests`, `bot_config`, `knowledge`, `regime`, `screener`, `strategies`, `symbols`
- Health endpoint: `GET /api/health`
- No authentication on any endpoint (open CORS)

## Real-Time Data Streams

**Upbit WebSocket:**
- `engine/data/upbit_ws.py` — `UpbitWebSocketManager` wraps `pyupbit.WebSocketManager`
- Subscribes to real-time ticker (price) stream for a list of KRW symbols
- Detects 5-minute candle boundary crossings and fires callback to trigger strategy scans
- Runs in daemon thread with exponential backoff reconnection (max 30s)

**Binance WebSocket:**
- `engine/data/binance_ws.py` — Binance real-time data stream (file present, details not read)

## Environment Configuration

**Required env vars (from `.env.example`):**
- `BINANCE_API_KEY` — Binance REST/WebSocket API key
- `BINANCE_SECRET_KEY` — Binance API secret
- `UPBIT_API_KEY` — Upbit REST API key
- `UPBIT_SECRET_KEY` — Upbit API secret

**Optional env vars:**
- `DISCORD_WEBHOOK_URL` — Overrides `config/discord.json` webhook URL

**Secrets location:**
- `.env` file at project root (loaded by systemd `EnvironmentFile=`, not committed)
- `config/discord.json` — Contains bot token (gitignore status unknown; `.example` version present)
- `config/broker.json` — References env vars via `${VAR}` syntax for exchange keys

---

*Integration audit: 2026-03-11*

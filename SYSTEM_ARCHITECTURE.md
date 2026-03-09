# Trading Runtime Architecture

## Goals

- Strategy changes should stay inside strategy modules or JSON definitions.
- Notification, execution, and bot control should be replaceable adapters.
- Runtime behaviour should be controllable with Discord commands.
- Development should remain testable with paper trading first.

## Structure

- `engine/domain/trading`
  - Core trading models and ports.
- `engine/application/trading`
  - Signal orchestration, pending approval flow, strategy evaluation.
- `engine/application/trading/providers`
  - Strategy source plugins such as JSON definitions.
- `engine/application/trading/scanner.py`
  - Multi-timeframe alert scanning and cooldown handling.
- `engine/infrastructure/runtime`
  - JSON-backed runtime state store.
- `engine/infrastructure/execution`
  - `PaperBroker` implementation.
- `engine/infrastructure/notifications`
  - Discord webhook notifier.
- `engine/plugins`
  - Broker/notifier/runtime store/strategy source registries.
- `engine/interfaces/discord`
  - Discord control bot and slash-command plugins.
- `engine/interfaces/scanner`
  - Background alert scanner entrypoint.
- `engine/interfaces/bootstrap.py`
  - Shared runtime assembly.

## Modes

- `alert_only`
  - Signals are sent to Discord only.
- `semi_auto`
  - Signals are stored as pending approvals. Execute with `/approve`.
- `auto`
  - Signals are executed immediately through the broker adapter.

## Discord Commands

- `/status`
- `/mode alert_only|semi_auto|auto`
- `/pause`
- `/resume`
- `/pending`
- `/approve <pending_id>`
- `/reject <pending_id>`
- `/analysis <symbol> <timeframe>`

Command files live under `engine/interfaces/discord/commands/` and are registered through `engine/interfaces/discord/registry.py`.

## CLI

- `python -m engine.cli runtime status`
- `python -m engine.cli runtime mode semi_auto`
- `python -m engine.cli runtime emit-sample --symbol BTC/USDT --action entry --side long --price 100000`
- `python -m engine.cli runtime evaluate strategies/active/momentum_rsi_macd_v1.json --symbol BTC/USDT --start 2024-01-01 --end 2024-03-01`
- `python -m engine.cli runtime run-bot`

Background alert scanning uses `config/alert_runtime.json` and routes alerts by timeframe webhook keys such as `tf_5m`, `tf_15m`, `tf_30m`, `tf_1h`.

## Secrets

- Prefer environment variables:
  - `DISCORD_BOT_TOKEN`
  - `DISCORD_WEBHOOK_URL`
- Fallback file: `config/discord.json`
- Example files:
  - `config/discord.example.json`
  - `config/runtime_state.example.json`

## Current Safety Boundary

- Automated execution is currently `paper` only.
- Real exchange adapters should be added only after paper mode is validated.
- Pending approvals and positions are persisted in `config/runtime_state.json`.

## Plugin Pattern

- New brokers: implement `BrokerPort`, register in `engine/plugins/runtime.py`
- New notifiers: implement `NotificationPort`, register in `engine/plugins/runtime.py`
- New strategy sources: implement `StrategySourcePort`, register in `engine/plugins/runtime.py`
- New Discord command groups: add a module in `engine/interfaces/discord/commands/`

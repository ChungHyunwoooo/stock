# Directory Map

## Read This First

- Runtime assembly: `engine/interfaces/bootstrap.py`
- Discord command entry: `engine/interfaces/discord/control_bot.py`
- Discord command groups: `engine/interfaces/discord/commands/`
- Alert scanner entry: `engine/interfaces/scanner/runtime.py`
- Trading orchestration: `engine/application/trading/orchestrator.py`
- Trading controls: `engine/application/trading/control.py`
- Strategy evaluation: `engine/application/trading/monitor.py`
- Multi-timeframe analysis and scanning: `engine/application/trading/scanner.py`
- Core models: `engine/domain/trading/models.py`
- Plugin registries: `engine/plugins/`

## Plugin Boundaries

- `engine/plugins/runtime.py`
  - broker plugins
  - notifier plugins
  - runtime store plugins
  - strategy source plugins
- `engine/interfaces/discord/commands/`
  - slash-command groups
- `engine/interfaces/scanner/`
  - alert scanner bootstrap
- `engine/application/trading/providers/`
  - strategy source loaders

## Change Guide

- Add a Discord command group:
  - create a file in `engine/interfaces/discord/commands/`
  - add the plugin object to `DEFAULT_COMMAND_PLUGINS`
- Add a new broker:
  - implement `BrokerPort`
  - register it in `engine/plugins/runtime.py`
- Add a new notifier:
  - implement `NotificationPort`
  - register it in `engine/plugins/runtime.py`
- Add a new strategy source:
  - implement `StrategySourcePort`
  - register it in `engine/plugins/runtime.py`
- Change alert payload once:
  - edit `engine/application/trading/presenters.py`
  - webhook alerts and `/analysis` both follow it

## Token Efficiency

- Prefer reading only the boundary file for the feature you are changing.
- Avoid loading legacy directories unless the task is explicitly about legacy code.
- For trading runtime work, start with:
  - `engine/domain/trading/`
  - `engine/application/trading/`
  - `engine/interfaces/discord/`
  - `engine/plugins/`


from __future__ import annotations

from functools import lru_cache

from discord import app_commands

from engine.data.provider_crypto import get_supported_crypto_exchanges, load_exchange_symbols

TIMEFRAME_CHOICES = ["all", "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
MODE_CHOICES = ["alert_only", "semi_auto", "auto"]
_DEFAULT_EXCHANGE = "binance"

def _filter_choices(values: list[str], current: str, limit: int = 25) -> list[app_commands.Choice[str]]:
    needle = current.lower().strip()
    startswith_matches = [value for value in values if value.lower().startswith(needle)] if needle else values
    remaining = [value for value in values if value not in startswith_matches]
    contains_matches = [value for value in remaining if needle in value.lower()] if needle else []
    matches = startswith_matches + contains_matches
    return [app_commands.Choice(name=value, value=value) for value in matches[:limit]]

def _get_runtime_control(interaction):
    return getattr(getattr(interaction, 'client', None), 'runtime_control', None)

def _get_preference_store(interaction):
    return getattr(getattr(interaction, 'client', None), 'user_preferences', None)

def infer_exchange_from_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    normalized = symbol.upper().strip()
    if normalized.startswith('KRW-') or normalized.endswith('/KRW'):
        return 'upbit'
    if any(quote in normalized for quote in ('/USDT', '/USDC', '/BTC', '/ETH')):
        return 'binance'
    return None

def resolve_exchange_for_interaction(interaction, symbol_hint: str | None = None, explicit_exchange: str | None = None) -> str:
    if explicit_exchange and explicit_exchange.strip():
        return explicit_exchange.strip()

    namespace_exchange = getattr(getattr(interaction, 'namespace', None), 'exchange', None)
    if namespace_exchange and str(namespace_exchange).strip():
        return str(namespace_exchange).strip()

    inferred = infer_exchange_from_symbol(symbol_hint)
    if inferred:
        return inferred

    preference_store = _get_preference_store(interaction)
    user = getattr(interaction, 'user', None)
    if preference_store is not None and user is not None:
        recent = preference_store.get_recent_exchange(user.id)
        if recent:
            return recent

    return _DEFAULT_EXCHANGE

async def exchange_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    exchanges = get_supported_crypto_exchanges()
    resolved = resolve_exchange_for_interaction(interaction, symbol_hint=getattr(getattr(interaction, 'namespace', None), 'symbol', None), explicit_exchange=current or None)
    ordered = [resolved] + [value for value in exchanges if value != resolved]
    return _filter_choices(ordered, current)

async def timeframe_autocomplete(_interaction, current: str) -> list[app_commands.Choice[str]]:
    return _filter_choices(TIMEFRAME_CHOICES, current)

async def mode_autocomplete(_interaction, current: str) -> list[app_commands.Choice[str]]:
    return _filter_choices(MODE_CHOICES, current)

async def symbol_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    exchange = resolve_exchange_for_interaction(interaction, symbol_hint=current)
    return _filter_choices(_cached_symbols(exchange), current)

async def pending_id_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    control = _get_runtime_control(interaction)
    if control is None:
        return []
    state = control.get_state()
    pending_items = [p for p in state.pending_orders if p.state.value == 'pending']
    values = [
        f"{item.pending_id} | {item.signal.symbol} | {item.signal.action.value} | {item.signal.timeframe}"
        for item in pending_items
    ]
    choices = _filter_choices(values, current)
    return [app_commands.Choice(name=choice.name, value=choice.value.split(' | ', 1)[0]) for choice in choices]

@lru_cache(maxsize=16)
def _cached_symbols(exchange: str) -> list[str]:
    return load_exchange_symbols(exchange)


# ---------------------------------------------------------------------------
# Lifecycle autocomplete (strategy + target status)
# ---------------------------------------------------------------------------

# Test hook: set to a LifecycleManager instance to override resolution.
_lifecycle_manager_override = None


def _get_lifecycle_manager(interaction):
    """Resolve LifecycleManager from interaction context or test override."""
    if _lifecycle_manager_override is not None:
        return _lifecycle_manager_override
    ctx = getattr(getattr(interaction, 'client', None), 'bot_context', None)
    if ctx is not None:
        return getattr(ctx, 'lifecycle_manager', None)
    return None


async def strategy_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete: list registered strategies as '{name} ({id})' choices."""
    mgr = _get_lifecycle_manager(interaction)
    if mgr is None:
        return []
    strategies = mgr.list_by_status(None)
    labeled = [f"{s.get('name', s['id'])} ({s['id']})" for s in strategies]
    ids = [s["id"] for s in strategies]

    needle = current.lower().strip()
    pairs = list(zip(labeled, ids))
    if needle:
        pairs = [(label, sid) for label, sid in pairs if needle in label.lower()]
    return [app_commands.Choice(name=label[:100], value=sid) for label, sid in pairs[:25]]


async def target_status_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete: list allowed target statuses for the selected strategy."""
    from engine.strategy.lifecycle_manager import ALLOWED_TRANSITIONS
    from engine.schema import StrategyStatus

    mgr = _get_lifecycle_manager(interaction)
    if mgr is None:
        return []

    strategy_id = getattr(getattr(interaction, 'namespace', None), 'strategy_id', None)
    if not strategy_id:
        return []

    try:
        entry = mgr.get_strategy(strategy_id)
    except Exception:
        return []

    try:
        current_status = StrategyStatus(entry.get("status"))
    except ValueError:
        return []

    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    values = sorted(s.value for s in allowed)
    return _filter_choices(values, current)

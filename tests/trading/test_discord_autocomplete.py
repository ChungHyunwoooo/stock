from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engine.domain.trading import PendingOrder, PendingState, SignalAction, TradeSide, TradingSignal
from engine.interfaces.discord.autocomplete import (
    exchange_autocomplete,
    infer_exchange_from_symbol,
    mode_autocomplete,
    pending_id_autocomplete,
    resolve_exchange_for_interaction,
    symbol_autocomplete,
    timeframe_autocomplete,
)


class DummyPrefs:
    def __init__(self, exchange: str | None = None) -> None:
        self.exchange = exchange

    def get_recent_exchange(self, _user_id):
        return self.exchange


def test_timeframe_autocomplete_filters_prefix():
    choices = __import__('asyncio').run(timeframe_autocomplete(None, '1'))
    values = [choice.value for choice in choices]
    assert '1m' in values
    assert '15m' in values
    assert '1h' in values
    assert '1d' in values


def test_mode_autocomplete_returns_runtime_modes():
    choices = __import__('asyncio').run(mode_autocomplete(None, 'a'))
    assert [choice.value for choice in choices] == ['alert_only', 'auto', 'semi_auto']


def test_exchange_autocomplete_prefers_resolved_exchange():
    interaction = SimpleNamespace(namespace=SimpleNamespace(symbol='KRW-BTC'), client=SimpleNamespace(user_preferences=DummyPrefs('bybit')), user=SimpleNamespace(id=1))
    with patch(
        'engine.interfaces.discord.autocomplete.get_supported_crypto_exchanges',
        return_value=['binance', 'bybit', 'okx', 'upbit'],
    ):
        choices = __import__('asyncio').run(exchange_autocomplete(interaction, ''))
    assert [choice.value for choice in choices][:2] == ['upbit', 'binance']


def test_symbol_autocomplete_uses_selected_exchange():
    interaction = SimpleNamespace(namespace=SimpleNamespace(exchange='bybit'), client=SimpleNamespace(user_preferences=DummyPrefs()), user=SimpleNamespace(id=1))
    with patch('engine.interfaces.discord.autocomplete._cached_symbols', return_value=['BTC/USDT', 'ETH/USDT']):
        choices = __import__('asyncio').run(symbol_autocomplete(interaction, 'et'))
    assert [choice.value for choice in choices] == ['ETH/USDT']


def test_symbol_autocomplete_uses_recent_exchange_when_missing():
    interaction = SimpleNamespace(namespace=SimpleNamespace(exchange=''), client=SimpleNamespace(user_preferences=DummyPrefs('okx')), user=SimpleNamespace(id=7))
    with patch('engine.interfaces.discord.autocomplete._cached_symbols', return_value=['BTC-USDT-SWAP', 'ETH-USDT-SWAP']):
        choices = __import__('asyncio').run(symbol_autocomplete(interaction, 'eth'))
    assert [choice.value for choice in choices] == ['ETH-USDT-SWAP']


def test_pending_id_autocomplete_uses_runtime_control():
    signal = TradingSignal(
        strategy_id='test:1.0',
        symbol='BTC/USDT',
        timeframe='15m',
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
    )
    pending = PendingOrder(pending_id='abc123', signal=signal, quantity=1.0, state=PendingState.pending)
    state = SimpleNamespace(pending_orders=[pending])
    control = SimpleNamespace(get_state=lambda: state)
    interaction = SimpleNamespace(client=SimpleNamespace(runtime_control=control))

    choices = __import__('asyncio').run(pending_id_autocomplete(interaction, 'abc'))

    assert [choice.value for choice in choices] == ['abc123']


def test_infer_exchange_from_symbol_handles_krw_and_usdt():
    assert infer_exchange_from_symbol('KRW-BTC') == 'upbit'
    assert infer_exchange_from_symbol('BTC/USDT') == 'binance'


def test_resolve_exchange_uses_recent_preference_when_no_input():
    interaction = SimpleNamespace(namespace=SimpleNamespace(exchange=''), client=SimpleNamespace(user_preferences=DummyPrefs('bybit')), user=SimpleNamespace(id=9))
    assert resolve_exchange_for_interaction(interaction, symbol_hint='') == 'bybit'

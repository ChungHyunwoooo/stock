"""브로커 테스트 — BaseBroker, PaperBroker, broker_factory, BinanceBroker, UpbitBroker.

실제 거래소 API 호출 없이 mock으로 테스트.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from typing import Any

import pytest

from engine.core.models import (
    OrderRequest,
    SignalAction,
    TradeSide,
    TradingRuntimeState,
)
from engine.execution.broker_base import BaseBroker
from engine.execution.paper_broker import PaperBroker
from engine.execution.broker_factory import create_broker, load_broker_config


# ── PaperBroker ─────────────────────────────────────────────


class TestPaperBroker:
    def _make_order(self, action="entry", side="long") -> OrderRequest:
        return OrderRequest(
            signal_id="sig001",
            symbol="KRW-BTC",
            action=SignalAction(action),
            side=TradeSide(side),
            quantity=0.01,
            price=50_000_000,
        )

    def test_entry_fills(self):
        broker = PaperBroker()
        state = TradingRuntimeState()
        order = self._make_order()
        result = broker.execute_order(order, state)
        assert result.status == "filled"
        assert result.notes == "paper"
        assert len(state.positions) == 1

    def test_exit_closes_position(self):
        broker = PaperBroker()
        state = TradingRuntimeState()
        broker.execute_order(self._make_order("entry"), state)
        broker.execute_order(self._make_order("exit"), state)
        closed = [p for p in state.positions if p.status.value == "closed"]
        assert len(closed) == 1

    def test_fetch_balance(self):
        broker = PaperBroker(initial_balance=10_000_000)
        balance = broker.fetch_balance()
        assert balance["exchange"] == "paper"
        assert balance["currency"] == "KRW"
        assert balance["total_equity"] == 10_000_000

    def test_fetch_total_equity(self):
        broker = PaperBroker(initial_balance=5_000_000)
        assert broker.fetch_total_equity() == 5_000_000

    def test_fetch_available(self):
        broker = PaperBroker(initial_balance=5_000_000)
        assert broker.fetch_available() == 5_000_000

    def test_cancel_always_true(self):
        broker = PaperBroker()
        assert broker.cancel_order("any", "KRW-BTC") is True

    def test_convert_symbol_passthrough(self):
        broker = PaperBroker()
        assert broker._convert_symbol("KRW-BTC") == "KRW-BTC"

    def test_validate_rejects_zero_quantity(self):
        broker = PaperBroker()
        order = self._make_order()
        order.quantity = 0
        with pytest.raises(ValueError, match="수량"):
            broker._validate_order(order)

    def test_validate_rejects_negative_price(self):
        broker = PaperBroker()
        order = self._make_order()
        order.price = -1
        with pytest.raises(ValueError, match="가격"):
            broker._validate_order(order)


# ── BaseBroker.calc_profit ──────────────────────────────────


class TestCalcProfit:
    def test_long_profit(self):
        r = BaseBroker.calc_profit("long", 50000, 51000, 1.0, 50, 51)
        assert r["profit_abs"] == pytest.approx(899, abs=1)
        assert r["profit_pct"] > 0

    def test_short_profit(self):
        r = BaseBroker.calc_profit("short", 50000, 49000, 1.0, 50, 49)
        assert r["profit_abs"] == pytest.approx(901, abs=1)

    def test_long_loss(self):
        r = BaseBroker.calc_profit("long", 50000, 49000, 1.0, 50, 49)
        assert r["profit_abs"] < 0

    def test_short_loss(self):
        r = BaseBroker.calc_profit("short", 50000, 51000, 1.0, 50, 51)
        assert r["profit_abs"] < 0

    def test_zero_quantity(self):
        r = BaseBroker.calc_profit("long", 50000, 51000, 0, 0, 0)
        assert r["profit_abs"] == 0
        assert r["profit_pct"] == 0


# ── broker_factory ──────────────────────────────────────────


class TestBrokerFactory:
    def test_create_paper(self, tmp_path):
        config = tmp_path / "broker.json"
        config.write_text('{"default": "paper", "exchanges": {}}')
        broker = create_broker(config_path=config)
        assert isinstance(broker, PaperBroker)

    def test_create_paper_explicit(self, tmp_path):
        config = tmp_path / "broker.json"
        config.write_text('{"default": "binance", "exchanges": {}}')
        broker = create_broker(exchange="paper", config_path=config)
        assert isinstance(broker, PaperBroker)

    def test_missing_config_defaults_paper(self, tmp_path):
        broker = create_broker(config_path=tmp_path / "nonexistent.json")
        assert isinstance(broker, PaperBroker)

    def test_missing_api_key_raises(self, tmp_path):
        config = tmp_path / "broker.json"
        config.write_text('{"default": "binance", "exchanges": {"binance": {"api_key": "", "secret": ""}}}')
        with pytest.raises(ValueError, match="API 키"):
            create_broker(config_path=config)

    def test_unsupported_exchange_raises(self, tmp_path):
        config = tmp_path / "broker.json"
        config.write_text('{"default": "paper", "exchanges": {}}')
        with pytest.raises(ValueError, match="지원하지 않는"):
            create_broker(exchange="kraken", config_path=config)

    @patch.dict("os.environ", {"TEST_KEY": "mykey", "TEST_SECRET": "mysecret"})
    def test_env_resolution(self, tmp_path):
        config = tmp_path / "broker.json"
        config.write_text(
            '{"default": "binance", "exchanges": {"binance": '
            '{"api_key": "${TEST_KEY}", "secret": "${TEST_SECRET}", '
            '"market_type": "spot", "testnet": true}}}'
        )
        from engine.execution.broker_factory import _resolve_env
        assert _resolve_env("${TEST_KEY}") == "mykey"


# ── BinanceBroker (mock ccxt) ───────────────────────────────


class TestBinanceBroker:
    def _make_order(self) -> OrderRequest:
        return OrderRequest(
            signal_id="sig001",
            symbol="BTC/USDT",
            action=SignalAction.entry,
            side=TradeSide.long,
            quantity=0.001,
            price=50000,
        )

    @patch("engine.execution.binance_broker.ccxt.binance")
    def test_spot_entry(self, mock_binance_cls):
        mock_exchange = MagicMock()
        mock_binance_cls.return_value = mock_exchange
        mock_exchange.create_order.return_value = {
            "id": "123",
            "average": 50000,
            "filled": 0.001,
            "fee": {"cost": 0.05},
        }

        from engine.execution.binance_broker import BinanceBroker
        broker = BinanceBroker("key", "secret", "spot", testnet=True)
        state = TradingRuntimeState()
        result = broker.execute_order(self._make_order(), state)

        assert result.status == "filled"
        assert "testnet" in result.notes
        mock_exchange.create_order.assert_called_once()

    @patch("engine.execution.binance_broker.ccxt.binanceusdm")
    def test_futures_symbol_conversion(self, mock_binanceusdm_cls):
        mock_exchange = MagicMock()
        mock_binanceusdm_cls.return_value = mock_exchange

        from engine.execution.binance_broker import BinanceBroker
        broker = BinanceBroker("key", "secret", "futures", testnet=True)
        assert broker._convert_symbol("BTC/USDT") == "BTC/USDT:USDT"
        assert broker._convert_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"

    @patch("engine.execution.binance_broker.ccxt.binance")
    def test_insufficient_funds(self, mock_binance_cls):
        import ccxt as real_ccxt
        mock_exchange = MagicMock()
        mock_binance_cls.return_value = mock_exchange
        mock_exchange.create_order.side_effect = real_ccxt.InsufficientFunds("not enough")

        from engine.execution.binance_broker import BinanceBroker
        broker = BinanceBroker("key", "secret", "spot", testnet=True)
        state = TradingRuntimeState()
        result = broker.execute_order(self._make_order(), state)

        assert result.status == "rejected"
        assert "잔고 부족" in result.notes

    @patch("engine.execution.binance_broker.ccxt.binance")
    def test_fetch_balance_spot(self, mock_binance_cls):
        mock_exchange = MagicMock()
        mock_binance_cls.return_value = mock_exchange
        mock_exchange.fetch_balance.return_value = {
            "total": {"USDT": 10000},
            "free": {"USDT": 8000},
            "used": {"USDT": 2000},
        }

        from engine.execution.binance_broker import BinanceBroker
        broker = BinanceBroker("key", "secret", "spot", testnet=True)
        balance = broker.fetch_balance()

        assert balance["currency"] == "USDT"
        assert balance["total_equity"] == 10000
        assert balance["available"] == 8000

    @patch("engine.execution.binance_broker.ccxt.binanceusdm")
    def test_set_leverage(self, mock_binanceusdm_cls):
        mock_exchange = MagicMock()
        mock_binanceusdm_cls.return_value = mock_exchange

        from engine.execution.binance_broker import BinanceBroker
        broker = BinanceBroker("key", "secret", "futures", testnet=True)
        broker.set_leverage("BTC/USDT", 10)

        mock_exchange.set_leverage.assert_called_once_with(10, "BTC/USDT:USDT")


# ── UpbitBroker (mock pyupbit) ──────────────────────────────


class TestUpbitBroker:
    def _make_order(self) -> OrderRequest:
        return OrderRequest(
            signal_id="sig001",
            symbol="BTC/KRW",
            action=SignalAction.entry,
            side=TradeSide.long,
            quantity=0.001,
            price=50_000_000,
        )

    @patch("engine.execution.upbit_broker.pyupbit.Upbit")
    def test_entry_buy(self, mock_upbit_cls):
        mock_upbit = MagicMock()
        mock_upbit_cls.return_value = mock_upbit
        mock_upbit.buy_market_order.return_value = {"uuid": "u001"}

        from engine.execution.upbit_broker import UpbitBroker
        broker = UpbitBroker("key", "secret")
        state = TradingRuntimeState()
        result = broker.execute_order(self._make_order(), state)

        assert result.status == "filled"
        mock_upbit.buy_market_order.assert_called_once()

    @patch("engine.execution.upbit_broker.pyupbit.Upbit")
    def test_exit_sell(self, mock_upbit_cls):
        mock_upbit = MagicMock()
        mock_upbit_cls.return_value = mock_upbit
        mock_upbit.sell_market_order.return_value = {"uuid": "u002"}

        from engine.execution.upbit_broker import UpbitBroker
        broker = UpbitBroker("key", "secret")
        state = TradingRuntimeState()

        order = self._make_order()
        order.action = SignalAction.exit
        result = broker.execute_order(order, state)

        assert result.status == "filled"
        mock_upbit.sell_market_order.assert_called_once()

    @patch("engine.execution.upbit_broker.pyupbit.Upbit")
    def test_order_failure(self, mock_upbit_cls):
        mock_upbit = MagicMock()
        mock_upbit_cls.return_value = mock_upbit
        mock_upbit.buy_market_order.return_value = {"error": {"message": "insufficient"}}

        from engine.execution.upbit_broker import UpbitBroker
        broker = UpbitBroker("key", "secret")
        state = TradingRuntimeState()
        result = broker.execute_order(self._make_order(), state)

        assert result.status == "failed"

    @patch("engine.execution.upbit_broker.pyupbit.Upbit")
    def test_symbol_conversion(self, mock_upbit_cls):
        mock_upbit = MagicMock()
        mock_upbit_cls.return_value = mock_upbit

        from engine.execution.upbit_broker import UpbitBroker
        broker = UpbitBroker("key", "secret")
        assert broker._convert_symbol("BTC/KRW") == "KRW-BTC"
        assert broker._convert_symbol("ETH/KRW") == "KRW-ETH"
        assert broker._convert_symbol("KRW-BTC") == "KRW-BTC"

    @patch("engine.execution.upbit_broker.pyupbit.Upbit")
    def test_fetch_balance(self, mock_upbit_cls):
        mock_upbit = MagicMock()
        mock_upbit_cls.return_value = mock_upbit
        mock_upbit.get_balances.return_value = [
            {"currency": "KRW", "balance": "1000000", "locked": "0", "avg_buy_price": "0"},
            {"currency": "BTC", "balance": "0.01", "locked": "0", "avg_buy_price": "50000000"},
        ]

        from engine.execution.upbit_broker import UpbitBroker
        broker = UpbitBroker("key", "secret")
        balance = broker.fetch_balance()

        assert balance["currency"] == "KRW"
        assert balance["total_equity"] == 1_000_000 + 500_000  # KRW + BTC평가
        assert balance["available"] == 1_000_000

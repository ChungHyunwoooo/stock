"""CcxtBroker + BrokerFactory 확장 테스트.

ccxt exchange를 mock하여 네트워크 호출 없이 테스트.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.core.models import (
    BrokerKind,
    OrderRequest,
    SignalAction,
    TradeSide,
)


# ── CcxtBroker 생성 ──────────────────────────────────────


class TestCcxtBrokerInit:
    """CcxtBroker 인스턴스 생성 테스트."""

    def test_bybit_creates_ccxt_bybit_instance(self):
        """Test 1: CcxtBroker("bybit") -> ccxt.bybit 인스턴스."""
        with patch("engine.execution.ccxt_broker.ccxt") as mock_ccxt:
            mock_exchange = MagicMock()
            mock_ccxt.bybit.return_value = mock_exchange

            from engine.execution.ccxt_broker import CcxtBroker

            broker = CcxtBroker("bybit", api_key="k", secret="s", testnet=True)

            mock_ccxt.bybit.assert_called_once()
            assert broker.exchange_name == "bybit"
            mock_exchange.set_sandbox_mode.assert_called_once_with(True)

    def test_okx_creates_ccxt_okx_with_password(self):
        """Test 2: CcxtBroker("okx", password=pw) -> ccxt.okx + passphrase."""
        with patch("engine.execution.ccxt_broker.ccxt") as mock_ccxt:
            mock_exchange = MagicMock()
            mock_ccxt.okx.return_value = mock_exchange

            from engine.execution.ccxt_broker import CcxtBroker

            broker = CcxtBroker(
                "okx", api_key="k", secret="s", password="pw", testnet=True,
            )

            call_kwargs = mock_ccxt.okx.call_args[0][0]
            assert call_kwargs["password"] == "pw"
            assert broker.exchange_name == "okx"


# ── CcxtBroker 메서드 ────────────────────────────────────


class TestCcxtBrokerMethods:
    """CcxtBroker 핵심 메서드 mock 테스트."""

    @pytest.fixture()
    def broker(self):
        with patch("engine.execution.ccxt_broker.ccxt") as mock_ccxt:
            mock_exchange = MagicMock()
            mock_ccxt.bybit.return_value = mock_exchange

            from engine.execution.ccxt_broker import CcxtBroker

            b = CcxtBroker("bybit", api_key="k", secret="s", testnet=True)
            b._exchange = mock_exchange
            yield b

    def test_place_order_calls_create_order(self, broker):
        """Test 3: _place_order -> ccxt create_order 호출."""
        broker._exchange.create_order.return_value = {
            "id": "order123",
            "average": 50000.0,
            "filled": 0.1,
            "fee": {"cost": 0.5},
        }

        order = OrderRequest(
            signal_id="sig1",
            symbol="BTC/USDT",
            action=SignalAction.entry,
            side=TradeSide.long,
            quantity=0.1,
            price=50000.0,
        )
        result = broker._place_order(order, "BTC/USDT")

        broker._exchange.create_order.assert_called_once()
        assert result.status == "filled"

    def test_fetch_raw_balance(self, broker):
        """Test 4: _fetch_raw_balance -> ccxt fetch_balance 정규화."""
        broker._exchange.fetch_balance.return_value = {
            "total": {"USDT": 10000},
            "free": {"USDT": 8000},
            "used": {"USDT": 2000},
        }

        raw = broker._fetch_raw_balance()

        broker._exchange.fetch_balance.assert_called_once()
        assert raw["total_equity"] == 10000.0
        assert raw["available"] == 8000.0
        assert raw["used"] == 2000.0

    def test_convert_symbol_passthrough(self, broker):
        """Test 5: _convert_symbol -> 심볼 그대로 반환 (ccxt unified)."""
        assert broker._convert_symbol("BTC/USDT") == "BTC/USDT"
        assert broker._convert_symbol("ETH/USDT") == "ETH/USDT"


# ── BrokerFactory 확장 ───────────────────────────────────


class TestBrokerFactoryExtended:
    """create_broker() bybit/okx 지원 테스트."""

    def test_create_broker_bybit(self, tmp_path):
        """Test 6: create_broker("bybit") -> CcxtBroker."""
        import json

        config = {
            "default": "paper",
            "exchanges": {
                "bybit": {
                    "api_key": "test_key",
                    "secret": "test_secret",
                    "market_type": "futures",
                    "testnet": True,
                },
            },
        }
        config_file = tmp_path / "broker.json"
        config_file.write_text(json.dumps(config))

        with patch("engine.execution.ccxt_broker.ccxt") as mock_ccxt:
            mock_ccxt.bybit.return_value = MagicMock()

            from engine.execution.broker_factory import create_broker

            broker = create_broker("bybit", config_path=config_file)

            from engine.execution.ccxt_broker import CcxtBroker

            assert isinstance(broker, CcxtBroker)
            assert broker.exchange_name == "bybit"

    def test_create_broker_okx(self, tmp_path):
        """Test 7: create_broker("okx") -> CcxtBroker."""
        import json

        config = {
            "default": "paper",
            "exchanges": {
                "okx": {
                    "api_key": "test_key",
                    "secret": "test_secret",
                    "password": "test_pass",
                    "market_type": "futures",
                    "testnet": True,
                },
            },
        }
        config_file = tmp_path / "broker.json"
        config_file.write_text(json.dumps(config))

        with patch("engine.execution.ccxt_broker.ccxt") as mock_ccxt:
            mock_ccxt.okx.return_value = MagicMock()

            from engine.execution.broker_factory import create_broker

            broker = create_broker("okx", config_path=config_file)

            from engine.execution.ccxt_broker import CcxtBroker

            assert isinstance(broker, CcxtBroker)
            assert broker.exchange_name == "okx"

    def test_create_broker_paper_unchanged(self):
        """Test 8: create_broker("paper") -> PaperBroker (하위 호환)."""
        from engine.execution.broker_factory import create_broker
        from engine.execution.paper_broker import PaperBroker

        broker = create_broker("paper")
        assert isinstance(broker, PaperBroker)

    def test_crypto_provider_bybit_ohlcv(self):
        """Test 9: CryptoProvider("bybit") 데이터 수급 경로 확인.

        _build_exchange에 lru_cache가 걸려 있으므로
        인스턴스 생성 후 _exchange를 직접 mock 교체.
        fetch_ohlcv의 while True 루프를 끊기 위해 side_effect 사용.
        """
        from engine.data.provider_crypto import CryptoProvider

        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.side_effect = [
            [[1700000000000, 100, 110, 90, 105, 1000]],
            [],  # 두 번째 호출에서 빈 리스트 → 루프 탈출
        ]

        provider = CryptoProvider.__new__(CryptoProvider)
        provider.exchange_name = "bybit"
        provider._exchange = mock_exchange

        df = provider.fetch_ohlcv("BTC/USDT", "2023-11-14", "2023-11-15")

        mock_exchange.fetch_ohlcv.assert_called()
        assert len(df) == 1
        assert "close" in df.columns

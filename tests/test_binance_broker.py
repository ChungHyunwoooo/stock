"""BinanceBroker 단위 테스트 — ccxt 완전 모킹.

실제 거래소 API 호출 없음. 모든 ccxt 호출은 MagicMock으로 대체.
"""

from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


# ── Fixture ─────────────────────────────────────────────────


@pytest.fixture
def broker():
    """BinanceBroker + mock ccxt.binanceusdm 쌍 반환.

    patch 컨텍스트 안에서 broker를 생성하고 yield — 테스트 종료까지 patch 유지.
    """
    with patch("engine.execution.binance_broker.ccxt") as mock_ccxt:
        mock_exchange = MagicMock()
        mock_ccxt.binanceusdm.return_value = mock_exchange
        mock_exchange.enable_demo_trading.return_value = None

        # BaseError는 테스트에서 side_effect로 쓸 수 있도록 진짜 클래스 연결
        import ccxt as real_ccxt
        mock_ccxt.BaseError = real_ccxt.BaseError

        from engine.execution.binance_broker import BinanceBroker
        b = BinanceBroker(
            api_key="test",
            secret="test",
            market_type="futures",
            testnet=True,
        )
        yield b, mock_exchange


# ── fetch_ohlcv ──────────────────────────────────────────────


class TestFetchOhlcv:
    def test_fetch_ohlcv_returns_dataframe(self, broker):
        """mock fetch_ohlcv → 50봉 DataFrame 반환."""
        b, mock_exchange = broker

        import time
        base_ts = int(time.time() * 1000) - 50 * 60000
        mock_exchange.fetch_ohlcv.return_value = [
            [base_ts + i * 60000, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 500.0]
            for i in range(50)
        ]

        df = b.fetch_ohlcv("BTC/USDT", "1m", limit=50)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 50
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "timestamp"

    def test_fetch_ohlcv_empty_on_error(self, broker):
        """ccxt.BaseError 발생 시 빈 DataFrame 반환.

        broker는 패치된 ccxt 모듈로 생성됐으므로, 실제 ccxt.BaseError를
        side_effect에 설정하고 mock_ccxt.BaseError에도 연결한다.
        """
        b, mock_exchange = broker

        import ccxt as real_ccxt
        mock_exchange.fetch_ohlcv.side_effect = real_ccxt.BaseError("network error")

        df = b.fetch_ohlcv("BTC/USDT", "1m", limit=50)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert set(df.columns) == {"open", "high", "low", "close", "volume"}


# ── load_market_info ─────────────────────────────────────────


class TestLoadMarketInfo:
    def _make_market(self) -> dict:
        return {
            "BTC/USDT:USDT": {
                "precision": {"price": 0.01, "amount": 0.001},
                "limits": {"amount": {"max": 1000.0, "min": 0.001}},
            }
        }

    def test_load_market_info_returns_dict(self, broker):
        """load_markets 호출 후 precision/limits 포함 dict 반환."""
        b, mock_exchange = broker
        mock_exchange.markets = self._make_market()

        info = b.load_market_info("BTC/USDT")

        assert isinstance(info, dict)
        assert info["price_precision"] == pytest.approx(0.01)
        assert info["qty_precision"] == pytest.approx(0.001)
        assert info["max_qty"] == pytest.approx(1000.0)
        assert info["min_qty"] == pytest.approx(0.001)
        mock_exchange.load_markets.assert_called_once()

    def test_load_market_info_cache(self, broker):
        """2회 호출 시 load_markets는 1회만 호출 (캐시 적중)."""
        b, mock_exchange = broker
        mock_exchange.markets = self._make_market()

        b.load_market_info("BTC/USDT")
        b.load_market_info("BTC/USDT")

        mock_exchange.load_markets.assert_called_once()


# ── clamp_quantity ────────────────────────────────────────────


class TestClampQuantity:
    def _inject_market_info(self, broker_obj, info: dict) -> None:
        """캐시에 직접 주입해서 load_markets 호출 없이 clamp_quantity 테스트."""
        broker_obj._market_info_cache["BTC/USDT:USDT"] = info

    def test_clamp_quantity_max(self, broker):
        """max_qty 초과 시 max_qty로 클램핑."""
        b, _ = broker
        self._inject_market_info(b, {
            "price_precision": 0.01,
            "qty_precision": 0.001,
            "max_qty": 10.0,
            "min_qty": 0.001,
        })

        result = b.clamp_quantity("BTC/USDT", 50.0)
        assert result == pytest.approx(10.0)

    def test_clamp_quantity_min(self, broker):
        """min_qty 미달 시 0.0 반환."""
        b, _ = broker
        self._inject_market_info(b, {
            "price_precision": 0.01,
            "qty_precision": 0.001,
            "max_qty": 1000.0,
            "min_qty": 0.01,
        })

        result = b.clamp_quantity("BTC/USDT", 0.005)
        assert result == 0.0

    def test_clamp_quantity_step(self, broker):
        """qty_step(qty_precision)에 맞게 내림 정렬."""
        b, _ = broker
        self._inject_market_info(b, {
            "price_precision": 0.01,
            "qty_precision": 0.01,
            "max_qty": 1000.0,
            "min_qty": 0.001,
        })

        # 0.157 → floor to 0.01 step → 0.15
        result = b.clamp_quantity("BTC/USDT", 0.157)
        assert result == pytest.approx(0.15, abs=1e-9)

    def test_clamp_quantity_no_info(self, broker):
        """시장 정보 없으면 원본 수량 그대로 반환."""
        b, mock_exchange = broker
        mock_exchange.markets = {}

        result = b.clamp_quantity("ETH/USDT", 3.14)
        assert result == pytest.approx(3.14)

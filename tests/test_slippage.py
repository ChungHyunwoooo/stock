"""Tests for SlippageModel, DepthCache, DepthCollector, FeeModel, ValidationResult."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# DepthCache tests
# ---------------------------------------------------------------------------

class TestDepthCache:
    """DepthCache Parquet read/write for depth statistics."""

    def test_get_stats_returns_dict_when_data_exists(self, tmp_path: Path) -> None:
        from engine.data.depth_cache import DepthCache

        cache = DepthCache(cache_dir=tmp_path, ttl_days=7)

        records = [
            {
                "symbol": "BTC/USDT",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "bid_depth_usd": 500_000.0,
                "ask_depth_usd": 480_000.0,
                "spread_pct": 0.0002,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "levels": 20,
            },
            {
                "symbol": "BTC/USDT",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "bid_depth_usd": 520_000.0,
                "ask_depth_usd": 500_000.0,
                "spread_pct": 0.0003,
                "best_bid": 50001.0,
                "best_ask": 50011.0,
                "levels": 20,
            },
        ]
        cache.save_snapshot(records)

        stats = cache.get_stats("BTC/USDT")
        assert stats is not None
        assert "avg_spread_pct" in stats
        assert "avg_depth_usd_10" in stats
        assert stats["avg_spread_pct"] == pytest.approx(0.00025, abs=1e-6)

    def test_get_stats_returns_none_when_no_data(self, tmp_path: Path) -> None:
        from engine.data.depth_cache import DepthCache

        cache = DepthCache(cache_dir=tmp_path, ttl_days=7)
        assert cache.get_stats("UNKNOWN/USDT") is None

    def test_save_snapshot_creates_parquet(self, tmp_path: Path) -> None:
        from engine.data.depth_cache import DepthCache

        cache = DepthCache(cache_dir=tmp_path, ttl_days=7)
        records = [
            {
                "symbol": "ETH/USDT",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "bid_depth_usd": 100_000.0,
                "ask_depth_usd": 95_000.0,
                "spread_pct": 0.0005,
                "best_bid": 3000.0,
                "best_ask": 3001.5,
                "levels": 20,
            },
        ]
        cache.save_snapshot(records)

        parquet_files = list(tmp_path.glob("*.parquet"))
        assert len(parquet_files) >= 1

    def test_get_stats_returns_none_when_ttl_expired(self, tmp_path: Path) -> None:
        import time
        from engine.data.depth_cache import DepthCache

        cache = DepthCache(cache_dir=tmp_path, ttl_days=0)  # immediate expiry

        records = [
            {
                "symbol": "BTC/USDT",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "bid_depth_usd": 500_000.0,
                "ask_depth_usd": 480_000.0,
                "spread_pct": 0.0002,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "levels": 20,
            },
        ]
        cache.save_snapshot(records)
        time.sleep(0.1)  # ensure TTL passed

        assert cache.get_stats("BTC/USDT") is None


# ---------------------------------------------------------------------------
# OrderbookDepthCollector tests
# ---------------------------------------------------------------------------

class TestOrderbookDepthCollector:
    """OrderbookDepthCollector with mocked ccxt."""

    def test_collect_snapshot_returns_stats_dict(self) -> None:
        from engine.data.depth_collector import OrderbookDepthCollector

        mock_exchange = MagicMock()
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[50000.0, 1.0], [49999.0, 2.0]],
            "asks": [[50001.0, 1.5], [50002.0, 0.5]],
        }

        collector = OrderbookDepthCollector.__new__(OrderbookDepthCollector)
        collector._exchange = mock_exchange
        collector._cache_dir = Path("/tmp/test_depth")

        result = collector.collect_snapshot("BTC/USDT", limit=20)
        assert result["symbol"] == "BTC/USDT"
        assert result["bid_depth_usd"] == pytest.approx(50000.0 * 1.0 + 49999.0 * 2.0)
        assert result["spread_pct"] == pytest.approx((50001.0 - 50000.0) / 50000.0)

    def test_collect_top_symbols_fetches_n_symbols(self) -> None:
        from engine.data.depth_collector import OrderbookDepthCollector

        mock_exchange = MagicMock()
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 1_000_000},
            "ETH/USDT": {"quoteVolume": 500_000},
            "DOGE/USDT": {"quoteVolume": 100_000},
        }
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[100.0, 10.0]],
            "asks": [[101.0, 10.0]],
        }

        collector = OrderbookDepthCollector.__new__(OrderbookDepthCollector)
        collector._exchange = mock_exchange
        collector._cache_dir = Path("/tmp/test_depth")

        results = collector.collect_top_symbols(n=2)
        assert len(results) == 2
        assert mock_exchange.load_markets.called


# ---------------------------------------------------------------------------
# SlippageModel tests
# ---------------------------------------------------------------------------

class TestNoSlippage:
    """NoSlippage always returns 0.0."""

    def test_returns_zero(self) -> None:
        from engine.backtest.slippage import NoSlippage

        model = NoSlippage()
        assert model.calculate_slippage("BTC/USDT", "buy", 10_000.0, 50000.0) == 0.0
        assert model.calculate_slippage("ETH/USDT", "sell", 5_000.0, 3000.0) == 0.0


class TestVolumeAdjustedSlippage:
    """VolumeAdjustedSlippage uses depth cache."""

    def test_returns_positive_slippage_proportional_to_size(self) -> None:
        from engine.backtest.slippage import VolumeAdjustedSlippage

        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = {
            "avg_spread_pct": 0.0002,
            "avg_depth_usd_10": 500_000.0,
        }

        model = VolumeAdjustedSlippage(depth_cache=mock_cache)
        slippage = model.calculate_slippage("BTC/USDT", "buy", 10_000.0, 50000.0)

        # base_spread (0.0002) + 0.1 * (10000 / 500000)
        expected = 0.0002 + 0.1 * (10_000.0 / 500_000.0)
        assert slippage == pytest.approx(expected)
        assert slippage > 0

    def test_fallback_when_no_depth_data(self) -> None:
        from engine.backtest.slippage import VolumeAdjustedSlippage

        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = None

        model = VolumeAdjustedSlippage(depth_cache=mock_cache)
        slippage = model.calculate_slippage("UNKNOWN/USDT", "buy", 10_000.0, 100.0)
        assert slippage == pytest.approx(0.001)

    def test_larger_order_gets_more_slippage(self) -> None:
        from engine.backtest.slippage import VolumeAdjustedSlippage

        mock_cache = MagicMock()
        mock_cache.get_stats.return_value = {
            "avg_spread_pct": 0.0002,
            "avg_depth_usd_10": 500_000.0,
        }

        model = VolumeAdjustedSlippage(depth_cache=mock_cache)
        small = model.calculate_slippage("BTC/USDT", "buy", 1_000.0, 50000.0)
        large = model.calculate_slippage("BTC/USDT", "buy", 100_000.0, 50000.0)
        assert large > small


# ---------------------------------------------------------------------------
# FeeModel tests
# ---------------------------------------------------------------------------

class TestFeeModel:
    """FeeModel loads from JSON config."""

    def test_load_and_get_binance_futures_taker(self, tmp_path: Path) -> None:
        from engine.backtest.fee_model import FeeModel

        fee_data = {
            "binance": {
                "spot": {"maker": 0.001, "taker": 0.001},
                "futures": {"maker": 0.0002, "taker": 0.0005},
            },
        }
        fee_file = tmp_path / "exchange_fees.json"
        fee_file.write_text(json.dumps(fee_data))

        model = FeeModel(fee_file)
        assert model.get_fee_rate("binance", "futures", "taker") == 0.0005
        assert model.get_fee_rate("binance", "spot", "maker") == 0.001

    def test_unknown_exchange_returns_default(self, tmp_path: Path) -> None:
        from engine.backtest.fee_model import FeeModel

        fee_data = {"binance": {"spot": {"maker": 0.001, "taker": 0.001}}}
        fee_file = tmp_path / "exchange_fees.json"
        fee_file.write_text(json.dumps(fee_data))

        model = FeeModel(fee_file)
        assert model.get_fee_rate("kraken", "spot", "taker") == 0.001

    def test_load_exchange_fees_utility(self, tmp_path: Path) -> None:
        from engine.backtest.fee_model import load_exchange_fees

        fee_data = {"upbit": {"spot": {"maker": 0.0005, "taker": 0.0005}}}
        fee_file = tmp_path / "exchange_fees.json"
        fee_file.write_text(json.dumps(fee_data))

        loaded = load_exchange_fees(fee_file)
        assert "upbit" in loaded
        assert loaded["upbit"]["spot"]["maker"] == 0.0005


# ---------------------------------------------------------------------------
# ValidationResult tests
# ---------------------------------------------------------------------------

class TestValidationResult:
    """WindowResult + ValidationResult dataclasses."""

    def test_window_result_constructs(self) -> None:
        from engine.backtest.validation_result import WindowResult

        wr = WindowResult(window_idx=0, is_sharpe=1.5, oos_sharpe=0.8, gap_ratio=0.53, passed=True)
        assert wr.window_idx == 0
        assert wr.is_sharpe == 1.5
        assert wr.passed is True

    def test_validation_result_constructs(self) -> None:
        from engine.backtest.validation_result import ValidationResult, WindowResult

        w = WindowResult(window_idx=0, is_sharpe=1.0, oos_sharpe=0.6, gap_ratio=0.6, passed=True)
        vr = ValidationResult(
            mode="walk_forward",
            windows=[w],
            overall_passed=True,
            summary={"n_windows": 1},
        )
        assert vr.mode == "walk_forward"
        assert len(vr.windows) == 1
        assert vr.overall_passed is True

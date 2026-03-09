"""Tests for swing scanner module — config, strategies, dedup, and scan loop."""

from __future__ import annotations

import json
import asyncio
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import numpy as np
import pandas as pd
import pytest

# Strategy tests require talib + ccxt + heavy engine deps; skip if not installed.
_has_heavy_deps = False
try:
    import ccxt as _ccxt_check  # noqa: F401
    import talib as _talib_check  # noqa: F401
    _has_heavy_deps = True
except ImportError:
    pass

requires_talib = pytest.mark.skipif(not _has_heavy_deps, reason="talib/ccxt not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def swing_df() -> pd.DataFrame:
    """200-row 1h OHLCV DataFrame with realistic swing patterns."""
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    np.random.seed(42)

    # Generate a trending then mean-reverting price series
    base = 50000.0
    returns = np.random.normal(0.0005, 0.008, n)
    # Add a trend shift in the middle
    returns[80:120] = np.random.normal(0.003, 0.008, 40)  # uptrend
    returns[140:170] = np.random.normal(-0.002, 0.008, 30)  # downtrend
    prices = base * np.cumprod(1 + returns)

    high = prices * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.005, n)))
    open_ = prices * (1 + np.random.normal(0, 0.002, n))

    volume = np.random.uniform(500_000, 5_000_000, n)
    # Volume spike around bar 100
    volume[98:103] = volume[98:103] * 3

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volume,
    }, index=idx)


@pytest.fixture
def swing_config():
    """Default SwingScannerConfig for testing."""
    from engine.strategy.swing_scanner import SwingScannerConfig
    return SwingScannerConfig()


@pytest.fixture
def golden_cross_df() -> pd.DataFrame:
    """DataFrame engineered to produce an EMA 20/50 golden cross at the last bar."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")

    # Downtrend then sharp reversal to trigger golden cross
    prices = np.concatenate([
        np.linspace(55000, 48000, 70),  # downtrend
        np.linspace(48000, 56000, 30),  # sharp uptrend
    ])

    high = prices * 1.005
    low = prices * 0.995
    open_ = prices * 0.999
    volume = np.ones(n) * 2_000_000
    volume[-5:] = 5_000_000  # volume spike at end

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volume,
    }, index=idx)


# ---------------------------------------------------------------------------
# SwingScannerConfig Tests
# ---------------------------------------------------------------------------

class TestSwingScannerConfig:
    def test_defaults(self):
        from engine.strategy.swing_scanner import SwingScannerConfig
        cfg = SwingScannerConfig()
        assert cfg.ema_fast == 20
        assert cfg.ema_slow == 50
        assert cfg.scan_interval_sec == 3600
        assert cfg.sl_atr_mult == 2.0
        assert cfg.tp1_atr_mult == 3.0
        assert cfg.discord_channel == "swing"
        assert cfg.primary_tf == "1h"

    def test_save_and_load(self, tmp_path):
        from engine.strategy.swing_scanner import SwingScannerConfig
        config_path = tmp_path / "swing_scanner.json"

        with patch("engine.strategy.swing_scanner.CONFIG_PATH", config_path):
            cfg = SwingScannerConfig(ema_fast=25, ema_slow=60)
            cfg.save()

            loaded = SwingScannerConfig.load()
            assert loaded.ema_fast == 25
            assert loaded.ema_slow == 60

    def test_load_ignores_unknown_keys(self, tmp_path):
        from engine.strategy.swing_scanner import SwingScannerConfig
        config_path = tmp_path / "swing_scanner.json"
        config_path.write_text(json.dumps({
            "ema_fast": 30,
            "unknown_key": "should_be_ignored",
        }))

        with patch("engine.strategy.swing_scanner.CONFIG_PATH", config_path):
            cfg = SwingScannerConfig.load()
            assert cfg.ema_fast == 30
            assert not hasattr(cfg, "unknown_key")

    def test_load_returns_default_on_missing_file(self, tmp_path):
        from engine.strategy.swing_scanner import SwingScannerConfig
        config_path = tmp_path / "nonexistent.json"

        with patch("engine.strategy.swing_scanner.CONFIG_PATH", config_path):
            cfg = SwingScannerConfig.load()
            assert cfg.ema_fast == 20  # default

    def test_all_strategies_toggled(self):
        from engine.strategy.swing_scanner import SwingScannerConfig
        cfg = SwingScannerConfig()
        assert cfg.enable_ema_cross is True
        assert cfg.enable_ichimoku is True
        assert cfg.enable_supertrend is True
        assert cfg.enable_macd_div is True
        assert cfg.enable_smc is True
        assert cfg.enable_bb_squeeze is True


# ---------------------------------------------------------------------------
# SwingSignalDedup Tests
# ---------------------------------------------------------------------------

class TestSwingSignalDedup:
    def test_new_signal_is_new(self, tmp_path):
        from engine.strategy.swing_scanner import SwingSignalDedup
        from engine.alerts.discord import Signal

        with patch("engine.strategy.swing_scanner.SENT_SIGNALS_PATH", tmp_path / "swing_sent.json"):
            dedup = SwingSignalDedup()
            sig = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                        entry=50000, stop_loss=48000, take_profits=[52000, 54000, 56000])
            assert dedup.is_new(sig) is True

    def test_duplicate_is_not_new(self, tmp_path):
        from engine.strategy.swing_scanner import SwingSignalDedup
        from engine.alerts.discord import Signal

        with patch("engine.strategy.swing_scanner.SENT_SIGNALS_PATH", tmp_path / "swing_sent.json"):
            dedup = SwingSignalDedup()
            sig = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                        entry=50000, stop_loss=48000, take_profits=[52000, 54000, 56000])
            dedup.mark_sent(sig)
            assert dedup.is_new(sig) is False

    def test_side_change_is_new(self, tmp_path):
        from engine.strategy.swing_scanner import SwingSignalDedup
        from engine.alerts.discord import Signal

        with patch("engine.strategy.swing_scanner.SENT_SIGNALS_PATH", tmp_path / "swing_sent.json"):
            dedup = SwingSignalDedup()
            sig1 = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                         entry=50000, stop_loss=48000, take_profits=[52000])
            dedup.mark_sent(sig1)

            sig2 = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="SHORT",
                         entry=50000, stop_loss=52000, take_profits=[48000])
            assert dedup.is_new(sig2) is True

    def test_price_move_3pct_is_new(self, tmp_path):
        from engine.strategy.swing_scanner import SwingSignalDedup
        from engine.alerts.discord import Signal

        with patch("engine.strategy.swing_scanner.SENT_SIGNALS_PATH", tmp_path / "swing_sent.json"):
            dedup = SwingSignalDedup()
            sig1 = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                         entry=50000, stop_loss=48000, take_profits=[52000])
            dedup.mark_sent(sig1)

            # 4% move → new signal
            sig2 = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                         entry=52000, stop_loss=50000, take_profits=[54000])
            assert dedup.is_new(sig2) is True

    def test_cleared_then_retriggered_is_new(self, tmp_path):
        from engine.strategy.swing_scanner import SwingSignalDedup
        from engine.alerts.discord import Signal

        with patch("engine.strategy.swing_scanner.SENT_SIGNALS_PATH", tmp_path / "swing_sent.json"):
            dedup = SwingSignalDedup()
            sig = Signal(strategy="SWING_EMA_CROSS", symbol="KRW-BTC", side="LONG",
                        entry=50000, stop_loss=48000, take_profits=[52000])
            dedup.mark_sent(sig)
            dedup.mark_cleared("KRW-BTC")
            assert dedup.is_new(sig) is True


# ---------------------------------------------------------------------------
# Strategy Build List Tests
# ---------------------------------------------------------------------------

class TestBuildStrategyList:
    def test_all_enabled(self, swing_config):
        from engine.strategy.swing_scanner import _build_swing_strategy_list
        strategies = _build_swing_strategy_list(swing_config)
        assert len(strategies) == 6

    def test_selective_disable(self):
        from engine.strategy.swing_scanner import SwingScannerConfig, _build_swing_strategy_list
        cfg = SwingScannerConfig(enable_ichimoku=False, enable_smc=False)
        strategies = _build_swing_strategy_list(cfg)
        assert len(strategies) == 4


# ---------------------------------------------------------------------------
# Individual Strategy Tests (with talib)
# ---------------------------------------------------------------------------

@requires_talib
class TestScanSwingEmaCross:
    def test_returns_none_on_short_data(self, swing_config):
        from engine.strategy.swing_scanner import scan_swing_ema_cross
        short_df = pd.DataFrame({
            "open": [100] * 10, "high": [101] * 10,
            "low": [99] * 10, "close": [100] * 10,
            "volume": [1000] * 10,
        }, index=pd.date_range("2024-01-01", periods=10, freq="1h"))
        result = scan_swing_ema_cross(short_df, "KRW-BTC", swing_config)
        assert result is None

    def test_signal_has_correct_timeframe(self, golden_cross_df, swing_config):
        """If a signal is produced, it should have timeframe='1h' and strategy='SWING_EMA_CROSS'."""
        from engine.strategy.swing_scanner import scan_swing_ema_cross
        # Provide favorable context
        ctx = {
            "adx": {"adx": 30, "is_trending": True, "trend_direction": "BULLISH"},
            "volume": {"vol_ratio": 2.0, "obv_trend": "RISING"},
            "structure": {"trend": "BULLISH"},
            "candle": {},
            "key_levels": {},
        }
        result = scan_swing_ema_cross(golden_cross_df, "KRW-BTC", swing_config, context=ctx)
        if result is not None:
            assert result.timeframe == "1h"
            assert result.strategy == "SWING_EMA_CROSS"
            assert result.side in ("LONG", "SHORT")


@requires_talib
class TestScanSwingIchimoku:
    def test_returns_none_on_short_data(self, swing_config):
        from engine.strategy.swing_scanner import scan_swing_ichimoku
        short_df = pd.DataFrame({
            "open": [100] * 30, "high": [101] * 30,
            "low": [99] * 30, "close": [100] * 30,
            "volume": [1000] * 30,
        }, index=pd.date_range("2024-01-01", periods=30, freq="1h"))
        result = scan_swing_ichimoku(short_df, "KRW-BTC", swing_config)
        assert result is None


@requires_talib
class TestScanSwingSupertrend:
    def test_returns_none_on_short_data(self, swing_config):
        from engine.strategy.swing_scanner import scan_swing_supertrend
        short_df = pd.DataFrame({
            "open": [100] * 10, "high": [101] * 10,
            "low": [99] * 10, "close": [100] * 10,
            "volume": [1000] * 10,
        }, index=pd.date_range("2024-01-01", periods=10, freq="1h"))
        result = scan_swing_supertrend(short_df, "KRW-BTC", swing_config)
        assert result is None


@requires_talib
class TestScanSwingMacdDiv:
    def test_returns_none_on_short_data(self, swing_config):
        from engine.strategy.swing_scanner import scan_swing_macd_div
        short_df = pd.DataFrame({
            "open": [100] * 30, "high": [101] * 30,
            "low": [99] * 30, "close": [100] * 30,
            "volume": [1000] * 30,
        }, index=pd.date_range("2024-01-01", periods=30, freq="1h"))
        result = scan_swing_macd_div(short_df, "KRW-BTC", swing_config)
        assert result is None


@requires_talib
class TestScanSwingSmc:
    def test_returns_none_without_smc_context(self, swing_df, swing_config):
        from engine.strategy.swing_scanner import scan_swing_smc
        result = scan_swing_smc(swing_df, "KRW-BTC", swing_config, context={})
        assert result is None

    def test_long_signal_with_choch_bullish(self, swing_df, swing_config):
        from engine.strategy.swing_scanner import scan_swing_smc
        ctx = {
            "smc": {"choch_bullish": True, "bullish_ob": True},
            "adx": {"adx": 25},
            "volume": {"vol_ratio": 1.5},
            "structure": {"trend": "BULLISH"},
            "candle": {},
            "key_levels": {},
        }
        result = scan_swing_smc(swing_df, "KRW-BTC", swing_config, context=ctx)
        if result is not None:
            assert result.strategy == "SWING_SMC"
            assert result.side == "LONG"
            assert result.timeframe == "1h"


@requires_talib
class TestScanSwingBbSqueeze:
    def test_returns_none_on_short_data(self, swing_config):
        from engine.strategy.swing_scanner import scan_swing_bb_squeeze
        short_df = pd.DataFrame({
            "open": [100] * 15, "high": [101] * 15,
            "low": [99] * 15, "close": [100] * 15,
            "volume": [1000] * 15,
        }, index=pd.date_range("2024-01-01", periods=15, freq="1h"))
        result = scan_swing_bb_squeeze(short_df, "KRW-BTC", swing_config)
        assert result is None


# ---------------------------------------------------------------------------
# Public API Tests
# ---------------------------------------------------------------------------

class TestSwingScannerAPI:
    def test_status_when_stopped(self):
        from engine.strategy.swing_scanner import status, is_running
        s = status()
        assert s["running"] is False
        assert s["scan_interval_sec"] == 3600
        assert is_running() is False

    def test_update_config(self, tmp_path):
        from engine.strategy.swing_scanner import SwingScannerConfig, update_config

        config_path = tmp_path / "swing_scanner.json"
        with patch("engine.strategy.swing_scanner.CONFIG_PATH", config_path), \
             patch("engine.strategy.swing_scanner._config", SwingScannerConfig()):
            cfg = update_config({"ema_fast": 25, "ema_slow": 60})
            assert cfg.ema_fast == 25
            assert cfg.ema_slow == 60
            # Verify persisted
            data = json.loads(config_path.read_text())
            assert data["ema_fast"] == 25

    def test_get_alert_history_empty(self):
        from engine.strategy import swing_scanner
        # Reset module state
        swing_scanner._alert_history = []
        assert swing_scanner.get_alert_history() == []

"""BTC_선물_봇 핵심 로직 테스트 — v2 (BaseBot 기반)."""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta

from engine.strategy.funding_contrarian import (
    FundingContrarianConfig,
    FundingContrarianScanner,
    FundingContrarianBot,
)
from engine.strategy.base_bot import BaseBot, BasePosition


class TestFundingContrarianConfig:
    def test_defaults(self):
        cfg = FundingContrarianConfig()
        assert cfg.fr_zscore_threshold == 1.5
        assert cfg.hold_hours == 50.0
        assert cfg.sl_pct == 5.0
        assert cfg.cooldown_hours == 24.0
        assert cfg.leverage == 3
        assert cfg.symbol == "BTC/USDT"
        assert cfg.mode == "paper"
        assert cfg.exchange == "binance"
        assert cfg.bot_name == "BTC_선물_봇"

    def test_custom(self):
        cfg = FundingContrarianConfig(fr_zscore_threshold=2.0, leverage=5, exchange="bybit")
        assert cfg.fr_zscore_threshold == 2.0
        assert cfg.leverage == 5
        assert cfg.exchange == "bybit"

    def test_inherits_base_config(self):
        cfg = FundingContrarianConfig()
        assert hasattr(cfg, "poll_interval_sec")
        assert hasattr(cfg, "mode")
        assert hasattr(cfg, "exchange")


class TestFundingContrarianScanner:
    def _make_scanner(self, threshold=1.5, lookback=150):
        cfg = FundingContrarianConfig(fr_zscore_threshold=threshold, fr_lookback=lookback)
        return FundingContrarianScanner(cfg)

    def _make_df(self, n=60, base_price=70000):
        prices = np.linspace(base_price, base_price * 1.01, n)
        return pd.DataFrame({
            "open": prices * 0.999,
            "high": prices * 1.001,
            "low": prices * 0.998,
            "close": prices,
            "volume": np.ones(n) * 1000,
        })

    def test_update_funding_rate(self):
        scanner = self._make_scanner()
        for i in range(200):
            scanner.update_funding_rate(0.0001)
        assert len(scanner.fr_history) == 200

    def test_fr_history_max_length(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(100):
            scanner.update_funding_rate(0.0001 * i)
        assert len(scanner.fr_history) == 60

    def test_zscore_insufficient_history(self):
        scanner = self._make_scanner(lookback=150)
        for i in range(100):
            scanner.update_funding_rate(0.0001)
        assert scanner.calc_fr_zscore() is None

    def test_zscore_calculation(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        z = scanner.calc_fr_zscore()
        assert z == 0.0

    def test_zscore_extreme_positive(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(9):
            scanner.update_funding_rate(0.0001)
        scanner.update_funding_rate(0.001)
        z = scanner.calc_fr_zscore()
        assert z is not None and z > 2.0

    def test_zscore_extreme_negative(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(9):
            scanner.update_funding_rate(0.0001)
        scanner.update_funding_rate(-0.001)
        z = scanner.calc_fr_zscore()
        assert z is not None and z < -2.0

    def test_event_detection_start(self):
        scanner = self._make_scanner(threshold=1.5)
        assert scanner.check_event(2.0) == "event_start"
        assert scanner._in_event is True

    def test_event_detection_continue(self):
        scanner = self._make_scanner(threshold=1.5)
        scanner.check_event(2.0)
        assert scanner.check_event(2.5) == "event_continue"

    def test_event_detection_end(self):
        scanner = self._make_scanner(threshold=1.5)
        scanner.check_event(2.0)
        assert scanner.check_event(0.5) == "event_end"
        assert scanner._in_event is False

    def test_event_no_event(self):
        scanner = self._make_scanner(threshold=1.5)
        assert scanner.check_event(0.5) == "no_event"

    def test_scan_returns_none_below_threshold(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        result = scanner.scan(df, fr_zscore=1.0)
        assert result is None

    def test_scan_returns_dict_above_threshold(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        result = scanner.scan(df, fr_zscore=2.0)
        assert result is not None
        assert result["side"] == "SHORT"
        assert "entry_price" in result
        assert "stop_loss" in result
        assert "fr_zscore" in result

    def test_scan_negative_zscore_long(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        result = scanner.scan(df, fr_zscore=-2.0)
        assert result is not None
        assert result["side"] == "LONG"

    def test_scan_only_on_event_start(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        sig1 = scanner.scan(df, fr_zscore=2.0)
        assert sig1 is not None
        sig2 = scanner.scan(df, fr_zscore=2.5)
        assert sig2 is None


class TestFundingContrarianBot:
    def test_is_base_bot(self):
        bot = FundingContrarianBot()
        assert isinstance(bot, BaseBot)

    def test_summary_empty(self):
        bot = FundingContrarianBot()
        s = bot.summary()
        assert s["trades"] == 0
        assert s["position"] is None
        assert s["mode"] == "paper"

    def test_uses_base_position(self):
        """봇이 BasePosition을 사용하는지."""
        bot = FundingContrarianBot()
        pos = BasePosition("BTC/USDT", "LONG", 70000, 66500, max_hold_hours=50)
        bot.position = pos
        s = bot.summary()
        assert s["position"]["symbol"] == "BTC/USDT"


class TestPosition:
    """BasePosition을 BTC봇 맥락에서 테스트."""

    @staticmethod
    def _recent():
        return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    def test_sl_long(self):
        pos = BasePosition("BTC/USDT", "LONG", 70000, 66500, entry_time=self._recent())
        should, reason, _ = pos.check_exit(71000, 66000, 67000)
        assert should and reason == "sl"

    def test_sl_short(self):
        pos = BasePosition("BTC/USDT", "SHORT", 70000, 73500, entry_time=self._recent())
        should, reason, _ = pos.check_exit(74000, 69000, 72000)
        assert should and reason == "sl"

    def test_no_exit(self):
        pos = BasePosition("BTC/USDT", "LONG", 70000, 66500, entry_time=self._recent())
        should, _, _ = pos.check_exit(71000, 69000, 70500)
        assert not should

    def test_timeout(self):
        pos = BasePosition("BTC/USDT", "LONG", 70000, 66500,
                          max_hold_hours=1, entry_time="2020-01-01T00:00:00+00:00")
        should, reason, _ = pos.check_exit(71000, 69000, 70000)
        assert should and reason == "timeout"

    def test_to_dict_from_dict(self):
        pos = BasePosition("BTC/USDT", "LONG", 70000, 66500,
                          bars_held=5, max_hold_hours=50,
                          entry_time="2026-01-01T00:00:00+00:00")
        d = pos.to_dict()
        restored = BasePosition.from_dict(d)
        assert restored.symbol == pos.symbol
        assert restored.entry_price == pos.entry_price

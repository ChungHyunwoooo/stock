"""알트_데일리_봇 핵심 로직 테스트 — v2 (BaseBot 기반)."""

import pytest
from datetime import datetime, timezone, timedelta

from engine.strategy.alt_momentum import (
    AltMomentumConfig,
    AltMomentumBot,
    VALIDATED_SYMBOLS,
)
from engine.strategy.base_bot import BaseBot, BasePosition


class TestAltMomentumConfig:
    def test_defaults(self):
        cfg = AltMomentumConfig()
        assert cfg.pump_threshold == 2.0
        assert cfg.vol_multiplier == 2.0
        assert cfg.tp_pct == 5.0
        assert cfg.sl_pct == 3.0
        assert cfg.hold_hours == 3.0
        assert cfg.max_positions == 5
        assert cfg.mode == "paper"
        assert cfg.exchange == "binance"
        assert cfg.bot_name == "알트_데일리_봇"

    def test_custom(self):
        cfg = AltMomentumConfig(tp_pct=7.0, sl_pct=4.0, max_positions=10, exchange="bybit")
        assert cfg.tp_pct == 7.0
        assert cfg.sl_pct == 4.0
        assert cfg.max_positions == 10
        assert cfg.exchange == "bybit"

    def test_validated_symbols_not_empty(self):
        assert len(VALIDATED_SYMBOLS) > 0
        assert all("/USDT" in s for s in VALIDATED_SYMBOLS)

    def test_default_symbols_from_validated(self):
        cfg = AltMomentumConfig()
        assert cfg.symbols == VALIDATED_SYMBOLS

    def test_inherits_base_config(self):
        cfg = AltMomentumConfig()
        assert hasattr(cfg, "poll_interval_sec")
        assert hasattr(cfg, "mode")
        assert hasattr(cfg, "exchange")


class TestAltMomentumBot:
    def test_is_base_bot(self):
        bot = AltMomentumBot()
        assert isinstance(bot, BaseBot)

    def test_summary_empty(self):
        bot = AltMomentumBot()
        s = bot.summary()
        assert s["trades"] == 0
        assert s["position_count"] == 0
        assert s["mode"] == "paper"

    def test_check_pump_true(self):
        bot = AltMomentumBot()
        data = {
            "close": 1.05, "prev_close": 1.00,
            "volume": 10000, "vol_history": [3000] * 20,
            "high": 1.06, "low": 0.99,
        }
        assert bot._check_pump(data) is True  # +5% > 2%, vol 10000 > 3000*2

    def test_check_pump_false_low_return(self):
        bot = AltMomentumBot()
        data = {
            "close": 1.01, "prev_close": 1.00,
            "volume": 10000, "vol_history": [3000] * 20,
            "high": 1.02, "low": 0.99,
        }
        assert bot._check_pump(data) is False  # +1% < 2%

    def test_check_pump_false_low_volume(self):
        bot = AltMomentumBot()
        data = {
            "close": 1.05, "prev_close": 1.00,
            "volume": 5000, "vol_history": [5000] * 20,
            "high": 1.06, "low": 0.99,
        }
        assert bot._check_pump(data) is False  # vol 5000 < 5000*2


class TestAltPosition:
    """BasePosition을 알트봇 맥락에서 테스트."""

    @staticmethod
    def _recent():
        return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    def test_tp_hit(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97,
                          take_profit=1.05, entry_time=self._recent())
        should, reason, price = pos.check_exit(1.06, 0.99, 1.04)
        assert should and reason == "tp" and price == 1.05

    def test_sl_hit(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97,
                          take_profit=1.05, entry_time=self._recent())
        should, reason, price = pos.check_exit(1.01, 0.96, 0.98)
        assert should and reason == "sl" and price == 0.97

    def test_no_exit(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97,
                          take_profit=1.05, entry_time=self._recent())
        should, _, _ = pos.check_exit(1.03, 0.98, 1.02)
        assert not should

    def test_tp_priority_over_sl(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97,
                          take_profit=1.05, entry_time=self._recent())
        should, reason, _ = pos.check_exit(1.10, 0.90, 1.0)
        assert should and reason == "tp"

    def test_timeout(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97,
                          take_profit=1.05, max_hold_hours=1,
                          entry_time="2020-01-01T00:00:00+00:00")
        should, reason, price = pos.check_exit(1.03, 0.98, 1.01)
        assert should and reason == "timeout" and price == 1.01

    def test_tick(self):
        pos = BasePosition("SUI/USDT", "LONG", 1.0, 0.97)
        pos.tick()
        pos.tick()
        assert pos.bars_held == 2

    def test_to_dict_from_dict(self):
        pos = BasePosition("ADA/USDT", "LONG", 0.45, 0.4365,
                          take_profit=0.4725, bars_held=2, max_hold_hours=3,
                          entry_time="2026-03-15T10:00:00+00:00")
        d = pos.to_dict()
        assert d["symbol"] == "ADA/USDT"
        restored = BasePosition.from_dict(d)
        assert restored.take_profit == 0.4725
        assert restored.bars_held == 2

    def test_position_prices_small_coin(self):
        entry = 0.0001
        tp = round(entry * 1.05, 10)
        sl = round(entry * 0.97, 10)
        assert tp == 0.000105
        assert sl == 0.000097

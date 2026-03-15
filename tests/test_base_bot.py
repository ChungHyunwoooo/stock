"""BaseBot / BasePosition / TradeRecord 테스트."""

import json
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

from engine.strategy.base_bot import (
    BaseBotConfig,
    BaseBot,
    BasePosition,
    TradeRecord,
)


class TestBasePosition:
    @staticmethod
    def _recent(minutes=5):
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    @staticmethod
    def _old(hours=100):
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # --- elapsed / timeout ---

    def test_elapsed_hours_recent(self):
        pos = BasePosition("X", "LONG", 100, 95, entry_time=self._recent(30))
        assert 0.4 < pos.elapsed_hours() < 0.6

    def test_elapsed_hours_no_entry_time(self):
        pos = BasePosition("X", "LONG", 100, 95)
        assert pos.elapsed_hours() == 0.0

    def test_is_timed_out_false(self):
        pos = BasePosition("X", "LONG", 100, 95, max_hold_hours=50,
                          entry_time=self._recent(5))
        assert pos.is_timed_out() is False

    def test_is_timed_out_true(self):
        pos = BasePosition("X", "LONG", 100, 95, max_hold_hours=1,
                          entry_time=self._old(2))
        assert pos.is_timed_out() is True

    # --- SL ---

    def test_check_sl_long_hit(self):
        pos = BasePosition("X", "LONG", 100, 95)
        assert pos.check_sl(101, 94) is True

    def test_check_sl_long_miss(self):
        pos = BasePosition("X", "LONG", 100, 95)
        assert pos.check_sl(101, 96) is False

    def test_check_sl_short_hit(self):
        pos = BasePosition("X", "SHORT", 100, 105)
        assert pos.check_sl(106, 99) is True

    def test_check_sl_short_miss(self):
        pos = BasePosition("X", "SHORT", 100, 105)
        assert pos.check_sl(104, 99) is False

    # --- TP ---

    def test_check_tp_long_hit(self):
        pos = BasePosition("X", "LONG", 100, 95, take_profit=110)
        assert pos.check_tp(111, 99) is True

    def test_check_tp_none(self):
        pos = BasePosition("X", "LONG", 100, 95, take_profit=None)
        assert pos.check_tp(200, 99) is False

    def test_check_tp_short_hit(self):
        pos = BasePosition("X", "SHORT", 100, 105, take_profit=90)
        assert pos.check_tp(101, 89) is True

    # --- check_exit priority: TP > SL > timeout ---

    def test_exit_tp_priority(self):
        pos = BasePosition("X", "LONG", 100, 90, take_profit=110,
                          entry_time=self._recent(5))
        should, reason, price = pos.check_exit(115, 85, 100)
        assert should and reason == "tp" and price == 110

    def test_exit_sl(self):
        pos = BasePosition("X", "LONG", 100, 95,
                          entry_time=self._recent(5))
        should, reason, price = pos.check_exit(101, 94, 96)
        assert should and reason == "sl" and price == 95

    def test_exit_timeout(self):
        pos = BasePosition("X", "LONG", 100, 50, max_hold_hours=1,
                          entry_time=self._old(2))
        should, reason, price = pos.check_exit(101, 99, 100.5)
        assert should and reason == "timeout" and price == 100.5

    def test_exit_none(self):
        pos = BasePosition("X", "LONG", 100, 95,
                          entry_time=self._recent(5))
        should, reason, price = pos.check_exit(101, 96, 100)
        assert not should

    # --- serialization ---

    def test_to_dict_from_dict(self):
        pos = BasePosition("BTC/USDT", "SHORT", 70000, 73500,
                          take_profit=66500, bars_held=10, max_hold_hours=50,
                          entry_time="2026-03-15T00:00:00+00:00",
                          extra={"leverage": 3})
        d = pos.to_dict()
        restored = BasePosition.from_dict(d)
        assert restored.symbol == "BTC/USDT"
        assert restored.side == "SHORT"
        assert restored.take_profit == 66500
        assert restored.extra == {"leverage": 3}

    def test_tick(self):
        pos = BasePosition("X", "LONG", 100, 95)
        pos.tick()
        pos.tick()
        assert pos.bars_held == 2


class TestTradeRecord:
    def test_to_dict(self):
        rec = TradeRecord(
            symbol="BTC/USDT", side="LONG",
            entry_price=70000, exit_price=72000,
            pnl_pct=2.86, bars_held=30,
            reason="tp", entry_time="t1", exit_time="t2",
            bot_name="BTC_선물_봇",
        )
        d = rec.to_dict()
        assert d["pnl_pct"] == 2.86
        assert d["bot_name"] == "BTC_선물_봇"


class TestBaseBotConfig:
    def test_defaults(self):
        cfg = BaseBotConfig()
        assert cfg.mode == "paper"
        assert cfg.exchange == "binance"
        assert cfg.poll_interval_sec == 60

    def test_custom(self):
        cfg = BaseBotConfig(bot_name="test", exchange="bybit", mode="live")
        assert cfg.bot_name == "test"
        assert cfg.exchange == "bybit"
        assert cfg.mode == "live"


class TestBaseBot:
    """BaseBot의 상태관리/루프 테스트 (구체 구현 mock)."""

    class MockBot(BaseBot):
        def __init__(self, config):
            super().__init__(config)
            self.init_called = False
            self.step_count = 0
            self.mock_data = {}

        def on_init(self):
            self.init_called = True

        def on_step(self):
            self.step_count += 1

        def get_state_data(self):
            return {"mock_data": self.mock_data, "step_count": self.step_count}

        def load_state_data(self, data):
            self.mock_data = data.get("mock_data", {})
            self.step_count = data.get("step_count", 0)

        def summary(self):
            return {"steps": self.step_count}

    def test_init_called_on_fresh_start(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=True) as f:
            cfg = BaseBotConfig(bot_name="test", state_file=f.name)
            # 파일 삭제해서 fresh start
            import os
            os.unlink(f.name)
            bot = self.MockBot(cfg)
            bot._load_state()
            assert bot.init_called is True

    def test_state_save_load(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            cfg = BaseBotConfig(bot_name="test", state_file=path)
            bot1 = self.MockBot(cfg)
            bot1.mock_data = {"key": "value"}
            bot1.step_count = 42
            bot1.trade_log = [{"pnl": 1.5}]
            bot1._save_state()

            # 새 인스턴스에서 복원
            bot2 = self.MockBot(cfg)
            bot2._load_state()
            assert bot2.mock_data == {"key": "value"}
            assert bot2.step_count == 42
            assert len(bot2.trade_log) == 1
        finally:
            import os
            os.unlink(path)

    def test_record_trade(self):
        cfg = BaseBotConfig(bot_name="test")
        bot = self.MockBot(cfg)
        rec = TradeRecord("BTC/USDT", "LONG", 70000, 72000, 2.86, 30,
                         "tp", "t1", "t2")
        bot._record_trade(rec)
        assert len(bot.trade_log) == 1
        assert bot.trade_log[0]["pnl_pct"] == 2.86
        assert bot.trade_log[0]["bot_name"] == "test"

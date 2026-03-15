"""알트_데일리_봇 핵심 로직 테스트 — API 호출 없이 순수 로직."""

import pytest
from datetime import datetime, timezone, timedelta

from engine.strategy.alt_momentum import (
    AltMomentumConfig,
    AltPosition,
    VALIDATED_SYMBOLS,
)


class TestAltMomentumConfig:
    def test_defaults(self):
        cfg = AltMomentumConfig()
        assert cfg.pump_threshold == 2.0
        assert cfg.vol_multiplier == 2.0
        assert cfg.tp_pct == 5.0
        assert cfg.sl_pct == 3.0
        assert cfg.max_hold_bars == 3
        assert cfg.max_positions == 5
        assert cfg.mode == "paper"

    def test_custom(self):
        cfg = AltMomentumConfig(tp_pct=7.0, sl_pct=4.0, max_positions=10)
        assert cfg.tp_pct == 7.0
        assert cfg.sl_pct == 4.0
        assert cfg.max_positions == 10

    def test_validated_symbols_not_empty(self):
        assert len(VALIDATED_SYMBOLS) > 0
        assert all("/USDT" in s for s in VALIDATED_SYMBOLS)

    def test_default_symbols_from_validated(self):
        cfg = AltMomentumConfig()
        assert cfg.symbols == VALIDATED_SYMBOLS


class TestAltPosition:
    @staticmethod
    def _recent_time():
        return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    def test_tp_hit(self):
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
            entry_time=self._recent_time(),
        )
        should, reason, price = pos.check_exit(high=1.06, low=0.99, close=1.04)
        assert should is True
        assert reason == "tp"
        assert price == 1.05

    def test_sl_hit(self):
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
            entry_time=self._recent_time(),
        )
        should, reason, price = pos.check_exit(high=1.01, low=0.96, close=0.98)
        assert should is True
        assert reason == "sl"
        assert price == 0.97

    def test_no_exit(self):
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
            entry_time=self._recent_time(),
        )
        should, reason, price = pos.check_exit(high=1.03, low=0.98, close=1.02)
        assert should is False

    def test_tp_priority_over_sl(self):
        """같은 봉에서 TP와 SL 동시 도달 → TP 우선."""
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
            entry_time=self._recent_time(),
        )
        should, reason, price = pos.check_exit(high=1.10, low=0.90, close=1.0)
        assert should is True
        assert reason == "tp"

    def test_timeout(self):
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
            max_hold=1,  # 1시간
            entry_time="2020-01-01T00:00:00+00:00",
        )
        should, reason, price = pos.check_exit(high=1.03, low=0.98, close=1.01)
        assert should is True
        assert reason == "timeout"
        assert price == 1.01

    def test_tick(self):
        pos = AltPosition(
            symbol="SUI/USDT", entry_price=1.0,
            tp_price=1.05, sl_price=0.97,
        )
        assert pos.bars_held == 0
        pos.tick()
        pos.tick()
        assert pos.bars_held == 2

    def test_to_dict_from_dict(self):
        pos = AltPosition(
            symbol="ADA/USDT", entry_price=0.45,
            tp_price=0.4725, sl_price=0.4365,
            bars_held=2, max_hold=3,
            entry_time="2026-03-15T10:00:00+00:00",
        )
        d = pos.to_dict()
        assert d["symbol"] == "ADA/USDT"
        assert d["entry_price"] == 0.45

        restored = AltPosition.from_dict(d)
        assert restored.symbol == pos.symbol
        assert restored.tp_price == pos.tp_price
        assert restored.bars_held == pos.bars_held

    def test_position_prices_calculated_correctly(self):
        """TP=5%, SL=3% 계산 검증."""
        entry = 100.0
        tp = round(entry * 1.05, 6)
        sl = round(entry * 0.97, 6)
        assert tp == 105.0
        assert sl == 97.0

        # 소수점 코인
        entry = 0.0001
        tp = round(entry * 1.05, 6)
        sl = round(entry * 0.97, 6)
        assert tp == 0.000105
        assert sl == 0.000097

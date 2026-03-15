"""BTC_선물_봇 핵심 로직 테스트 — API 호출 없이 순수 로직."""

import numpy as np
import pandas as pd
import pytest

from engine.strategy.funding_contrarian import (
    FundingContrarianConfig,
    FundingContrarianScanner,
    Position,
    Signal,
)


class TestFundingContrarianConfig:
    def test_defaults(self):
        cfg = FundingContrarianConfig()
        assert cfg.fr_zscore_threshold == 1.5
        assert cfg.hold_bars == 50
        assert cfg.sl_pct == 5.0
        assert cfg.cooldown_bars == 24
        assert cfg.leverage == 3
        assert cfg.symbol == "BTC/USDT"
        assert cfg.mode == "paper"

    def test_custom(self):
        cfg = FundingContrarianConfig(fr_zscore_threshold=2.0, leverage=5)
        assert cfg.fr_zscore_threshold == 2.0
        assert cfg.leverage == 5


class TestFundingContrarianScanner:
    def _make_scanner(self, threshold=1.5, lookback=150):
        cfg = FundingContrarianConfig(fr_zscore_threshold=threshold, fr_lookback=lookback)
        return FundingContrarianScanner(cfg)

    def _make_df(self, n=60, base_price=70000):
        """EMA 계산 가능한 최소 DataFrame."""
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
        assert len(scanner._fr_history) == 200

    def test_fr_history_max_length(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(100):
            scanner.update_funding_rate(0.0001 * i)
        assert len(scanner._fr_history) == 60  # lookback + 50

    def test_zscore_insufficient_history(self):
        scanner = self._make_scanner(lookback=150)
        for i in range(100):
            scanner.update_funding_rate(0.0001)
        assert scanner.calc_fr_zscore() is None

    def test_zscore_calculation(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        # 마지막 값이 평균과 같으면 z=0
        z = scanner.calc_fr_zscore()
        assert z == 0.0

    def test_zscore_extreme_positive(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(9):
            scanner.update_funding_rate(0.0001)
        scanner.update_funding_rate(0.001)  # 10배 높은 값
        z = scanner.calc_fr_zscore()
        assert z is not None
        assert z > 2.0  # 극단 양수

    def test_zscore_extreme_negative(self):
        scanner = self._make_scanner(lookback=10)
        for i in range(9):
            scanner.update_funding_rate(0.0001)
        scanner.update_funding_rate(-0.001)  # 극단 음수
        z = scanner.calc_fr_zscore()
        assert z is not None
        assert z < -2.0

    def test_event_detection_start(self):
        scanner = self._make_scanner(threshold=1.5)
        result = scanner.check_event(2.0)
        assert result == "event_start"
        assert scanner._in_event is True

    def test_event_detection_continue(self):
        scanner = self._make_scanner(threshold=1.5)
        scanner.check_event(2.0)  # start
        result = scanner.check_event(2.5)  # continue
        assert result == "event_continue"

    def test_event_detection_end(self):
        scanner = self._make_scanner(threshold=1.5)
        scanner.check_event(2.0)  # start
        result = scanner.check_event(0.5)  # end (below threshold)
        assert result == "event_end"
        assert scanner._in_event is False

    def test_event_no_event(self):
        scanner = self._make_scanner(threshold=1.5)
        result = scanner.check_event(0.5)
        assert result == "no_event"

    def test_scan_returns_none_below_threshold(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        signal = scanner.scan(df, fr_zscore=1.0)
        assert signal is None

    def test_scan_returns_signal_above_threshold(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        signal = scanner.scan(df, fr_zscore=2.0)
        # 양수 z → SHORT (역발상)
        assert signal is not None
        assert signal.side == "SHORT"

    def test_scan_negative_zscore_long(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        signal = scanner.scan(df, fr_zscore=-2.0)
        assert signal is not None
        assert signal.side == "LONG"

    def test_scan_only_on_event_start(self):
        scanner = self._make_scanner(threshold=1.5, lookback=10)
        for i in range(10):
            scanner.update_funding_rate(0.0001)
        df = self._make_df()
        # 첫 번째: event_start → 신호 발생
        sig1 = scanner.scan(df, fr_zscore=2.0)
        assert sig1 is not None
        # 두 번째: event_continue → 신호 없음
        sig2 = scanner.scan(df, fr_zscore=2.5)
        assert sig2 is None


class TestPosition:
    @staticmethod
    def _recent_time():
        """충분히 최근 시간 (timeout 안 걸리게)."""
        from datetime import datetime, timezone, timedelta
        return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    def test_sl_long(self):
        pos = Position(symbol="BTC/USDT", side="LONG",
                      entry_price=70000, stop_loss=66500,
                      entry_time=self._recent_time())
        should, reason = pos.should_exit(71000, 66000)  # low < SL
        assert should is True
        assert reason == "stop_loss"

    def test_sl_short(self):
        pos = Position(symbol="BTC/USDT", side="SHORT",
                      entry_price=70000, stop_loss=73500,
                      entry_time=self._recent_time())
        should, reason = pos.should_exit(74000, 69000)  # high > SL
        assert should is True
        assert reason == "stop_loss"

    def test_no_exit(self):
        pos = Position(symbol="BTC/USDT", side="LONG",
                      entry_price=70000, stop_loss=66500,
                      entry_time=self._recent_time())
        should, reason = pos.should_exit(71000, 69000)
        assert should is False

    def test_timeout(self):
        """과거 entry_time → timeout 트리거."""
        pos = Position(symbol="BTC/USDT", side="LONG",
                      entry_price=70000, stop_loss=66500,
                      max_hold=1,  # 1시간
                      entry_time="2020-01-01T00:00:00+00:00")
        should, reason = pos.should_exit(71000, 69000)
        assert should is True
        assert reason == "hold_timeout"

    def test_tick(self):
        pos = Position(symbol="BTC/USDT", side="LONG",
                      entry_price=70000, stop_loss=66500)
        pos.tick()
        pos.tick()
        assert pos.bars_held == 2

    def test_to_dict_from_dict(self):
        pos = Position(symbol="BTC/USDT", side="LONG",
                      entry_price=70000, stop_loss=66500,
                      bars_held=5, max_hold=50, entry_time="2026-01-01T00:00:00+00:00")
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.symbol == pos.symbol
        assert restored.entry_price == pos.entry_price
        assert restored.bars_held == pos.bars_held

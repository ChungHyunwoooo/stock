"""MTFConfirmationGate 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.core.models import TradeSide
from engine.strategy.mtf_filter import MTFConfig, MTFConfirmationGate, _timeframe_to_minutes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(prices: list[float]) -> pd.DataFrame:
    """close 가격 리스트로 간단한 OHLCV DataFrame 생성."""
    return pd.DataFrame({
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [100.0] * len(prices),
    })


def _mock_provider(prices: list[float]) -> MagicMock:
    """fetch_ohlcv가 prices 기반 DataFrame을 반환하는 mock provider."""
    provider = MagicMock()
    provider.fetch_ohlcv.return_value = _make_ohlcv(prices)
    return provider


# ---------------------------------------------------------------------------
# MTFConfig
# ---------------------------------------------------------------------------

class TestMTFConfig:
    def test_defaults(self):
        cfg = MTFConfig()
        assert cfg.enabled is False
        assert cfg.higher_timeframe == "4h"
        assert cfg.ema_period == 20
        assert cfg.lookback_bars == 50


# ---------------------------------------------------------------------------
# Disabled / No Provider
# ---------------------------------------------------------------------------

class TestDisabledFilter:
    def test_disabled_always_passes(self):
        gate = MTFConfirmationGate(MTFConfig(enabled=False))
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True
        assert "disabled" in reason.lower()

    def test_no_provider_passes(self):
        gate = MTFConfirmationGate(MTFConfig(enabled=True), data_provider=None)
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True
        assert "No data provider" in reason


# ---------------------------------------------------------------------------
# Signal TF >= Higher TF
# ---------------------------------------------------------------------------

class TestTimeframeComparison:
    def test_signal_tf_gte_higher_tf(self):
        """signal TF가 상위 TF 이상이면 MTF 불필요."""
        provider = _mock_provider([100.0] * 30)
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h"),
            data_provider=provider,
        )
        # 4h signal vs 4h higher -> pass
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "4h")
        assert ok is True
        assert "Signal TF >= Higher TF" in reason

        # 1d signal vs 4h higher -> pass
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.short, "1d")
        assert ok is True


# ---------------------------------------------------------------------------
# Direction alignment
# ---------------------------------------------------------------------------

class TestDirectionAlignment:
    """현재가 vs EMA 방향 정렬 테스트."""

    def test_price_above_ema_long_aligned(self):
        """현재가 > EMA + side=LONG -> 정렬 (True)."""
        # 상승 추세: 가격이 점진적으로 올라감 -> 현재가 > EMA
        prices = list(range(50, 80))  # 30 bars, 50->79
        provider = _mock_provider(prices)
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True
        assert "Aligned" in reason

    def test_price_above_ema_short_blocked(self):
        """현재가 > EMA + side=SHORT -> 반대 (False)."""
        prices = list(range(50, 80))
        provider = _mock_provider(prices)
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.short, "5m")
        assert ok is False
        assert "Against" in reason

    def test_price_below_ema_short_aligned(self):
        """현재가 < EMA + side=SHORT -> 정렬 (True)."""
        # 하락 추세: 가격이 점진적으로 내려감 -> 현재가 < EMA
        prices = list(range(80, 50, -1))  # 30 bars, 80->51
        provider = _mock_provider(prices)
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.short, "5m")
        assert ok is True
        assert "Aligned" in reason

    def test_price_below_ema_long_blocked(self):
        """현재가 < EMA + side=LONG -> 반대 (False)."""
        prices = list(range(80, 50, -1))
        provider = _mock_provider(prices)
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is False
        assert "Against" in reason


# ---------------------------------------------------------------------------
# Error handling (fail-open)
# ---------------------------------------------------------------------------

class TestFailOpen:
    def test_fetch_exception_allows_signal(self):
        """데이터 조회 실패 시 신호 허용 (fail-open)."""
        provider = MagicMock()
        provider.fetch_ohlcv.side_effect = RuntimeError("Connection timeout")
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h"),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True
        assert "fetch failed" in reason.lower()

    def test_empty_dataframe_allows_signal(self):
        """빈 DataFrame 반환 시 허용."""
        provider = MagicMock()
        provider.fetch_ohlcv.return_value = pd.DataFrame()
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h"),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True
        assert "Insufficient" in reason

    def test_insufficient_data_allows_signal(self):
        """데이터가 EMA 기간보다 적으면 허용."""
        provider = _mock_provider([100.0] * 5)  # only 5 bars, ema_period=20
        gate = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        ok, reason = gate.check_alignment("BTCUSDT", TradeSide.long, "5m")
        assert ok is True


# ---------------------------------------------------------------------------
# _timeframe_to_minutes
# ---------------------------------------------------------------------------

class TestTimeframeToMinutes:
    @pytest.mark.parametrize("tf,expected", [
        ("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60),
        ("4h", 240), ("1d", 1440),
    ])
    def test_known_timeframes(self, tf, expected):
        assert _timeframe_to_minutes(tf) == expected

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            _timeframe_to_minutes("2d")


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

from engine.application.trading import TradingControlService, TradingOrchestrator
from engine.core import SignalAction, TradingMode, TradingSignal
from engine.execution import PaperBroker
from engine.notifications import MemoryNotifier
from engine.core import JsonRuntimeStore


def _make_signal(side: TradeSide = TradeSide.long) -> TradingSignal:
    return TradingSignal(
        strategy_id="test:1.0",
        symbol="BTC/USDT",
        timeframe="5m",
        action=SignalAction.entry,
        side=side,
        entry_price=100.0,
        stop_loss=95.0,
        take_profits=[110.0],
        reason="test signal",
    )


class TestOrchestratorMTFIntegration:
    """Orchestrator + MTFConfirmationGate 통합 테스트."""

    def test_aligned_signal_executes(self, tmp_path):
        """정렬된 신호 -> 주문 실행."""
        store = JsonRuntimeStore(tmp_path / "runtime.json")
        notifier = MemoryNotifier()
        broker = PaperBroker()
        control = TradingControlService(store, notifier, broker)
        control.set_mode(TradingMode.auto)

        # 상승 추세 -> LONG 정렬
        prices = list(range(50, 80))
        provider = _mock_provider(prices)
        mtf = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        orchestrator = TradingOrchestrator(store, notifier, broker, mtf_filter=mtf)
        state = orchestrator.process_signal(_make_signal(TradeSide.long))

        assert len(state.executions) == 1

    def test_opposing_signal_blocked(self, tmp_path):
        """반대 방향 신호 -> 차단, notifier에 [MTF] 메시지."""
        store = JsonRuntimeStore(tmp_path / "runtime.json")
        notifier = MemoryNotifier()
        broker = PaperBroker()
        control = TradingControlService(store, notifier, broker)
        control.set_mode(TradingMode.auto)

        # 상승 추세 -> SHORT 반대
        prices = list(range(50, 80))
        provider = _mock_provider(prices)
        mtf = MTFConfirmationGate(
            MTFConfig(enabled=True, higher_timeframe="4h", ema_period=20),
            data_provider=provider,
        )
        orchestrator = TradingOrchestrator(store, notifier, broker, mtf_filter=mtf)
        state = orchestrator.process_signal(_make_signal(TradeSide.short))

        assert len(state.executions) == 0
        mtf_messages = [t for t in notifier.messages if "[MTF]" in t]
        assert len(mtf_messages) == 1
        assert "blocked" in mtf_messages[0].lower()

    def test_no_mtf_filter_backward_compatible(self, tmp_path):
        """mtf_filter=None -> 기존 동작 유지."""
        store = JsonRuntimeStore(tmp_path / "runtime.json")
        notifier = MemoryNotifier()
        broker = PaperBroker()
        control = TradingControlService(store, notifier, broker)
        control.set_mode(TradingMode.auto)

        orchestrator = TradingOrchestrator(store, notifier, broker, mtf_filter=None)
        state = orchestrator.process_signal(_make_signal())

        assert len(state.executions) == 1

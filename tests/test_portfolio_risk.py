"""PortfolioRiskManager 단위 테스트 — 상관관계 게이트 + Risk Parity 배분."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine.strategy.portfolio_risk import PortfolioRiskConfig, PortfolioRiskManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(seed: int, n: int = 100) -> pd.Series:
    """재현 가능한 랜덤 수익률 시계열."""
    rng = np.random.RandomState(seed)
    return pd.Series(rng.randn(n) * 0.01)


def _make_correlated_returns(base: pd.Series, noise_scale: float = 0.1, seed: int = 99) -> pd.Series:
    """base와 높은 상관관계를 갖는 수익률 생성."""
    rng = np.random.RandomState(seed)
    noise = rng.randn(len(base)) * base.std() * noise_scale
    return pd.Series(base.values + noise)


# ---------------------------------------------------------------------------
# Test 1: 높은 상관관계 → 차단
# ---------------------------------------------------------------------------

class TestCorrelationGate:
    def test_high_correlation_blocks(self):
        """상관관계 0.7 초과 시 두 번째 진입 차단."""
        mgr = PortfolioRiskManager()
        base = _make_returns(seed=42, n=100)
        correlated = _make_correlated_returns(base, noise_scale=0.1, seed=99)

        # 상관관계 확인
        assert base.corr(correlated) > 0.7

        mgr.register_strategy("strat_a", base)
        allowed, reason = mgr.check_correlation_gate("strat_b", correlated)
        assert allowed is False
        assert "blocked" in reason

    # Test 2: 낮은 상관관계 → 허용
    def test_low_correlation_allows(self):
        """상관관계 0.5 미만 시 진입 허용."""
        mgr = PortfolioRiskManager()
        s1 = _make_returns(seed=42, n=100)
        s2 = _make_returns(seed=7, n=100)

        assert abs(s1.corr(s2)) < 0.7

        mgr.register_strategy("strat_a", s1)
        allowed, reason = mgr.check_correlation_gate("strat_b", s2)
        assert allowed is True
        assert reason == "passed"

    # Test 3: enabled=False → 항상 허용
    def test_disabled_always_allows(self):
        """enabled=False 시 상관관계 무관하게 허용."""
        config = PortfolioRiskConfig(enabled=False)
        mgr = PortfolioRiskManager(config=config)
        base = _make_returns(seed=42)
        correlated = _make_correlated_returns(base)

        mgr.register_strategy("strat_a", base)
        allowed, reason = mgr.check_correlation_gate("strat_b", correlated)
        assert allowed is True
        assert reason == "gate_disabled"

    # Test 4: 전략별 오버라이드 임계치
    def test_strategy_override_threshold(self):
        """전략별 오버라이드 0.95 설정 시 기본 임계치 초과해도 허용."""
        config = PortfolioRiskConfig(
            correlation_threshold=0.7,
            strategy_overrides={"strat_b": 0.95},
        )
        mgr = PortfolioRiskManager(config=config)
        base = _make_returns(seed=42, n=100)
        # noise_scale=0.5 → corr ~0.89 (기본 0.7 초과, 오버라이드 0.95 미달)
        correlated = _make_correlated_returns(base, noise_scale=0.5, seed=99)

        corr_val = base.corr(correlated)
        assert corr_val > 0.7, f"corr={corr_val:.4f}, expected > 0.7"
        assert corr_val < 0.95, f"corr={corr_val:.4f}, expected < 0.95"

        mgr.register_strategy("strat_a", base)
        allowed, reason = mgr.check_correlation_gate("strat_b", correlated)
        assert allowed is True
        assert reason == "passed"

    # Test 5: 활성 전략 없으면 항상 허용
    def test_no_active_strategies_allows(self):
        """활성 전략이 없으면 항상 허용."""
        mgr = PortfolioRiskManager()
        s1 = _make_returns(seed=42)
        allowed, reason = mgr.check_correlation_gate("strat_a", s1)
        assert allowed is True
        assert reason == "no_active_strategies"


# ---------------------------------------------------------------------------
# Test 6-7: Risk Parity 배분
# ---------------------------------------------------------------------------

class TestAllocationWeights:
    def test_get_allocation_weights_returns_parity(self):
        """get_allocation_weights() 호출 시 Risk Parity 기반 배분 반환."""
        mgr = PortfolioRiskManager()
        mgr.register_strategy("strat_a", _make_returns(seed=42, n=100))
        mgr.register_strategy("strat_b", _make_returns(seed=7, n=100))

        mgr.refresh_weights()
        weights = mgr.get_allocation_weights()

        assert set(weights.keys()) == {"strat_a", "strat_b"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert all(w > 0 for w in weights.values())

    def test_refresh_weights_updates(self):
        """refresh_weights() 호출 시 최신 수익률로 배분 재계산."""
        mgr = PortfolioRiskManager()
        mgr.register_strategy("strat_a", _make_returns(seed=42, n=100))
        mgr.register_strategy("strat_b", _make_returns(seed=7, n=100))
        mgr.refresh_weights()
        w1 = dict(mgr.get_allocation_weights())

        # 세 번째 전략 추가 후 재계산
        mgr.register_strategy("strat_c", _make_returns(seed=123, n=100))
        mgr.refresh_weights()
        w2 = mgr.get_allocation_weights()

        assert "strat_c" in w2
        assert len(w2) == 3
        assert abs(sum(w2.values()) - 1.0) < 1e-6

    def test_get_allocation_weights_equal_when_no_refresh(self):
        """refresh 전에는 균등 배분 반환."""
        mgr = PortfolioRiskManager()
        mgr.register_strategy("strat_a", _make_returns(seed=42))
        mgr.register_strategy("strat_b", _make_returns(seed=7))

        weights = mgr.get_allocation_weights()
        assert abs(weights["strat_a"] - 0.5) < 1e-6
        assert abs(weights["strat_b"] - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Test: 차단 시 notifier 호출
# ---------------------------------------------------------------------------

class TestNotification:
    def test_blocked_sends_notification(self):
        """차단 시 notifier.send_text() 호출."""
        notifier = MagicMock()
        mgr = PortfolioRiskManager(notifier=notifier)
        base = _make_returns(seed=42)
        correlated = _make_correlated_returns(base)

        mgr.register_strategy("strat_a", base)
        mgr.check_correlation_gate("strat_b", correlated)

        notifier.send_text.assert_called_once()
        call_msg = notifier.send_text.call_args[0][0]
        assert "blocked" in call_msg.lower() or "차단" in call_msg

    def test_allowed_no_notification(self):
        """허용 시 notifier 미호출."""
        notifier = MagicMock()
        mgr = PortfolioRiskManager(notifier=notifier)
        s1 = _make_returns(seed=42)
        s2 = _make_returns(seed=7)

        mgr.register_strategy("strat_a", s1)
        mgr.check_correlation_gate("strat_b", s2)

        notifier.send_text.assert_not_called()

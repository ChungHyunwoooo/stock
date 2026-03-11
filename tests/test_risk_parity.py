"""Risk Parity 자본 배분 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.strategy.risk_parity import RiskParityConfig, calculate_risk_parity_weights


def _make_returns(n_days: int = 60, volatility: float = 0.02, seed: int = 42) -> pd.Series:
    """테스트용 일별 수익률 시리즈 생성."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0, volatility, n_days))


class TestRiskParity:
    def test_equal_volatility_equal_weights(self):
        """Test 1: 2개 전략, 동일 변동성 -> 동등 배분 (각 ~0.5)."""
        returns = {
            "strat_a": _make_returns(60, 0.02, seed=1),
            "strat_b": _make_returns(60, 0.02, seed=2),
        }
        weights = calculate_risk_parity_weights(returns)
        assert abs(weights["strat_a"] - 0.5) < 0.1
        assert abs(weights["strat_b"] - 0.5) < 0.1
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_higher_volatility_lower_weight(self):
        """Test 2: 3개 전략, 전략A 변동성 2배 -> 전략A 배분 낮음."""
        returns = {
            "strat_a": _make_returns(60, 0.04, seed=1),  # 2x volatility
            "strat_b": _make_returns(60, 0.02, seed=2),
            "strat_c": _make_returns(60, 0.02, seed=3),
        }
        weights = calculate_risk_parity_weights(returns)
        assert weights["strat_a"] < weights["strat_b"]
        assert weights["strat_a"] < weights["strat_c"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_single_strategy_capped(self):
        """Test 3: 전략 1개 -> 배분 1.0 (max_allocation cap 이내)."""
        returns = {
            "only": _make_returns(60, 0.02),
        }
        weights = calculate_risk_parity_weights(returns)
        assert abs(weights["only"] - 1.0) < 1e-6

    def test_max_allocation_cap(self):
        """Test 4: max_allocation_per_strategy=0.4 -> 어떤 전략도 0.4 초과 불가."""
        returns = {
            "strat_a": _make_returns(60, 0.01, seed=1),  # low vol -> wants high weight
            "strat_b": _make_returns(60, 0.05, seed=2),  # high vol -> low weight
        }
        config = RiskParityConfig(max_allocation_per_strategy=0.4)
        weights = calculate_risk_parity_weights(returns, config=config)
        for w in weights.values():
            assert w <= 0.4 + 1e-6
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_empty_or_nan_returns_fallback(self):
        """Test 5: 빈 데이터 / NaN만 -> 균등 배분 fallback."""
        # empty
        returns_empty = {
            "strat_a": pd.Series([], dtype=float),
            "strat_b": pd.Series([], dtype=float),
        }
        w1 = calculate_risk_parity_weights(returns_empty)
        assert abs(w1["strat_a"] - 0.5) < 1e-6
        assert abs(w1["strat_b"] - 0.5) < 1e-6

        # NaN only
        returns_nan = {
            "strat_a": pd.Series([float("nan")] * 10),
            "strat_b": pd.Series([float("nan")] * 10),
        }
        w2 = calculate_risk_parity_weights(returns_nan)
        assert abs(w2["strat_a"] - 0.5) < 1e-6

    def test_singular_covariance_fallback(self):
        """Test 6: singular 공분산 행렬 -> 균등 배분 fallback."""
        # 동일 수익률 -> 완전 상관 -> singular covariance
        shared = _make_returns(60, 0.02, seed=1)
        returns = {
            "strat_a": shared.copy(),
            "strat_b": shared.copy(),
        }
        weights = calculate_risk_parity_weights(returns)
        # Should not crash, should return valid weights summing to 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6

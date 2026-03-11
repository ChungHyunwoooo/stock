"""WalkForwardValidator 테스트 -- IS/OOS 분할 + 성과 갭 판정."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.backtest.walk_forward import WalkForwardValidator
from engine.backtest.validation_result import ValidationResult, WindowResult


class TestWalkForwardValidator:
    """WalkForwardValidator 핵심 동작 검증."""

    def _monotonic_equity(self, n: int = 500) -> pd.Series:
        """단조 증가 equity curve -- 모든 윈도우 PASS 기대."""
        return pd.Series(np.linspace(100, 200, n))

    def _random_walk_equity(self, n: int = 500, seed: int = 42) -> pd.Series:
        """랜덤 워크 equity curve -- 일부 윈도우 FAIL 기대."""
        rng = np.random.default_rng(seed)
        returns = rng.normal(0.0, 0.02, n - 1)
        prices = [100.0]
        for r in returns:
            prices.append(prices[-1] * (1 + r))
        return pd.Series(prices)

    def test_monotonic_all_pass(self):
        """단조 증가 equity curve => 전체 PASS."""
        validator = WalkForwardValidator()
        result = validator.validate(self._monotonic_equity())

        assert isinstance(result, ValidationResult)
        assert result.mode == "walk_forward"
        assert result.overall_passed is True
        assert len(result.windows) == 5
        for w in result.windows:
            assert w.passed is True
            assert w.gap_ratio >= 0.5

    def test_random_walk_some_fail(self):
        """랜덤 워크 equity curve => 일부 윈도우 FAIL."""
        validator = WalkForwardValidator()
        result = validator.validate(self._random_walk_equity())

        assert isinstance(result, ValidationResult)
        assert result.mode == "walk_forward"
        assert len(result.windows) == 5
        # 랜덤 워크에서 모든 윈도우가 통과하기는 매우 어려움
        fail_count = sum(1 for w in result.windows if not w.passed)
        assert fail_count >= 1, "Random walk should fail at least one window"

    def test_too_short_raises(self):
        """Equity curve가 너무 짧으면 ValueError."""
        validator = WalkForwardValidator(n_windows=5)
        short_curve = pd.Series(np.linspace(100, 110, 30))  # < 5 * 10 = 50
        with pytest.raises(ValueError, match="too short"):
            validator.validate(short_curve)

    def test_custom_gap_threshold_zero_all_pass(self):
        """gap_threshold=0.0 => 모든 윈도우 PASS (gap_ratio >= 0 항상 충족)."""
        validator = WalkForwardValidator(gap_threshold=0.0)
        result = validator.validate(self._random_walk_equity())

        assert result.overall_passed is True
        for w in result.windows:
            assert w.passed is True

    def test_result_mode(self):
        """결과 mode == 'walk_forward' 확인."""
        validator = WalkForwardValidator()
        result = validator.validate(self._monotonic_equity())
        assert result.mode == "walk_forward"

    def test_windows_count(self):
        """windows 개수 == n_windows 확인."""
        for n_windows in [3, 5, 7]:
            validator = WalkForwardValidator(n_windows=n_windows)
            result = validator.validate(self._monotonic_equity(700))
            assert len(result.windows) == n_windows

    def test_gap_ratio_accuracy(self):
        """gap_ratio = oos_sharpe / is_sharpe 계산 정확도."""
        validator = WalkForwardValidator()
        result = validator.validate(self._monotonic_equity())

        for w in result.windows:
            if w.is_sharpe != 0:
                expected_gap = w.oos_sharpe / w.is_sharpe
                assert abs(w.gap_ratio - expected_gap) < 1e-10
            else:
                assert w.gap_ratio == 0.0

    def test_overall_passed_requires_all_windows(self):
        """overall_passed = all(w.passed) -- 하나라도 FAIL이면 False."""
        validator = WalkForwardValidator(gap_threshold=0.99)
        result = validator.validate(self._random_walk_equity())

        if any(not w.passed for w in result.windows):
            assert result.overall_passed is False

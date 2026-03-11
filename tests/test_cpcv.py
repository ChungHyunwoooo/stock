"""CPCVValidator -- Combinatorial Purged Cross-Validation 검증 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.backtest.cpcv import CPCVValidator
from engine.backtest.validation_result import ValidationResult, WindowResult


def _monotonic_equity(n: int = 300, start: float = 100.0) -> pd.Series:
    """단조 증가 equity curve 생성."""
    return pd.Series(start + np.arange(n, dtype=float) * 0.5)


def _random_equity(n: int = 300, start: float = 100.0, seed: int = 42) -> pd.Series:
    """랜덤 워크 equity curve."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.01, n - 1)
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return pd.Series(prices)


class TestCPCVValidator:
    """CPCVValidator 기본 동작 테스트."""

    def test_monotonic_high_pass_rate(self) -> None:
        """단조 증가 curve → high pass_rate, overall_passed=True."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        assert result.overall_passed is True
        pass_rate = result.summary["pass_rate"]
        assert pass_rate >= 0.5

    def test_mode_is_cpcv(self) -> None:
        """결과 mode가 'cpcv'."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        assert result.mode == "cpcv"

    def test_returns_validation_result(self) -> None:
        """ValidationResult 타입 반환."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        assert isinstance(result, ValidationResult)

    def test_summary_contains_n_paths_and_pass_rate(self) -> None:
        """summary에 n_paths, pass_rate 포함."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        assert "n_paths" in result.summary
        assert "pass_rate" in result.summary

    def test_paths_count_positive(self) -> None:
        """paths(windows) 개수 > 0."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        assert len(result.windows) > 0
        assert result.summary["n_paths"] > 0

    def test_too_short_curve_raises_value_error(self) -> None:
        """너무 짧은 equity curve → ValueError."""
        validator = CPCVValidator()
        short_curve = pd.Series([100.0, 101.0, 102.0])

        with pytest.raises(ValueError):
            validator.validate(short_curve)

    def test_same_interface_as_walk_forward(self) -> None:
        """WalkForwardValidator와 동일 equity curve에 대해 둘 다 ValidationResult 반환."""
        from engine.backtest.walk_forward import WalkForwardValidator

        equity = _monotonic_equity()
        wf_result = WalkForwardValidator().validate(equity)
        cpcv_result = CPCVValidator().validate(equity)

        assert isinstance(wf_result, ValidationResult)
        assert isinstance(cpcv_result, ValidationResult)
        assert wf_result.mode == "walk_forward"
        assert cpcv_result.mode == "cpcv"

    def test_windows_are_window_result(self) -> None:
        """각 window가 WindowResult 타입."""
        validator = CPCVValidator()
        result = validator.validate(_monotonic_equity())

        for w in result.windows:
            assert isinstance(w, WindowResult)

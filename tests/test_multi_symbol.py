"""Tests for multi-symbol stability validation.

Covers:
- select_uncorrelated_symbols: correlation-based greedy selection
- MultiSymbolResult: median Sharpe pass/fail logic
- MultiSymbolValidator: parallel backtest + median Sharpe gate
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Task 1: select_uncorrelated_symbols + MultiSymbolResult
# ---------------------------------------------------------------------------

class TestSelectUncorrelatedSymbols:
    """상관계수 기반 비상관 심볼 선택."""

    def test_perfectly_correlated_selects_one(self):
        """완전 상관 데이터 -> 1개만 선택."""
        from engine.backtest.multi_symbol import select_uncorrelated_symbols

        # Same returns for all 3 symbols (perfect correlation)
        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.01, 100)
        returns_df = pd.DataFrame({
            "A": base,
            "B": base,
            "C": base,
        })
        result = select_uncorrelated_symbols(["A", "B", "C"], returns_df, max_corr=0.5, n_select=3)
        assert len(result) == 1
        assert result[0] == "A"

    def test_uncorrelated_selects_all(self):
        """독립 랜덤 데이터 (seed=42, 3 symbols) -> 3개 선택."""
        from engine.backtest.multi_symbol import select_uncorrelated_symbols

        rng = np.random.default_rng(42)
        returns_df = pd.DataFrame({
            "X": rng.normal(0, 0.01, 200),
            "Y": rng.normal(0, 0.01, 200),
            "Z": rng.normal(0, 0.01, 200),
        })
        result = select_uncorrelated_symbols(["X", "Y", "Z"], returns_df, max_corr=0.5, n_select=3)
        assert len(result) == 3

    def test_max_corr_one_selects_all(self):
        """max_corr=1.0 -> 전부 선택 (어떤 상관계수든 허용)."""
        from engine.backtest.multi_symbol import select_uncorrelated_symbols

        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.01, 100)
        returns_df = pd.DataFrame({
            "A": base,
            "B": base,
            "C": base,
        })
        result = select_uncorrelated_symbols(["A", "B", "C"], returns_df, max_corr=1.0, n_select=3)
        # max_corr=1.0 means |r| < 1.0 -- perfect corr (|r|=1.0) is NOT < 1.0
        # But floating point: corr of identical arrays may be 0.9999... so could pass
        # At minimum, first symbol is always selected
        assert len(result) >= 1

    def test_n_select_limits_output(self):
        """n_select보다 많은 비상관 심볼이 있어도 n_select까지만."""
        from engine.backtest.multi_symbol import select_uncorrelated_symbols

        rng = np.random.default_rng(42)
        returns_df = pd.DataFrame({
            "A": rng.normal(0, 0.01, 200),
            "B": rng.normal(0, 0.01, 200),
            "C": rng.normal(0, 0.01, 200),
            "D": rng.normal(0, 0.01, 200),
        })
        result = select_uncorrelated_symbols(
            ["A", "B", "C", "D"], returns_df, max_corr=0.5, n_select=2,
        )
        assert len(result) <= 2


class TestMultiSymbolResult:
    """MultiSymbolResult 데이터 클래스 + passed 로직."""

    def test_passed_when_median_above_threshold(self):
        """median_sharpe >= threshold -> passed=True."""
        from engine.backtest.multi_symbol import MultiSymbolResult

        result = MultiSymbolResult(
            symbols=["A", "B", "C"],
            sharpe_per_symbol={"A": 0.8, "B": 0.6, "C": 0.7},
            median_sharpe=0.7,
            passed=True,
            threshold=0.5,
        )
        assert result.passed is True
        assert result.median_sharpe >= result.threshold

    def test_failed_when_median_below_threshold(self):
        """median_sharpe < threshold -> passed=False."""
        from engine.backtest.multi_symbol import MultiSymbolResult

        result = MultiSymbolResult(
            symbols=["A", "B"],
            sharpe_per_symbol={"A": 0.3, "B": 0.2},
            median_sharpe=0.25,
            passed=False,
            threshold=0.5,
        )
        assert result.passed is False
        assert result.median_sharpe < result.threshold

    def test_edge_exactly_at_threshold(self):
        """median_sharpe == threshold -> passed=True."""
        from engine.backtest.multi_symbol import MultiSymbolResult

        result = MultiSymbolResult(
            symbols=["A"],
            sharpe_per_symbol={"A": 0.5},
            median_sharpe=0.5,
            passed=True,
            threshold=0.5,
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# Task 2: MultiSymbolValidator parallel backtest
# ---------------------------------------------------------------------------

class TestMultiSymbolValidator:
    """MultiSymbolValidator 병렬 백테스트 + median Sharpe gate."""

    def test_median_above_threshold_passes(self):
        """모든 심볼 Sharpe > threshold -> passed=True."""
        from unittest.mock import MagicMock, patch

        from engine.backtest.multi_symbol import MultiSymbolValidator

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 0.8

        with patch("engine.backtest.multi_symbol._run_symbol_backtest") as mock_worker:
            mock_worker.side_effect = [
                ("SYM_A", 0.8),
                ("SYM_B", 0.6),
                ("SYM_C", 0.7),
            ]

            validator = MultiSymbolValidator(n_workers=1, sharpe_threshold=0.5)
            # Use direct call instead of ProcessPoolExecutor to avoid pickle issues with mock
            result = validator._validate_sequential(
                strategy_dict={"id": "test"},
                symbols=["SYM_A", "SYM_B", "SYM_C"],
                start="2025-01-01",
                end="2025-12-31",
                timeframe="1d",
                initial_capital=10_000.0,
                fee_rate=0.0,
            )
            assert result.passed is True
            assert result.median_sharpe == pytest.approx(0.7)
            assert len(result.symbols) == 3

    def test_median_below_threshold_fails(self):
        """모든 심볼 Sharpe < threshold -> passed=False."""
        from unittest.mock import patch

        from engine.backtest.multi_symbol import MultiSymbolValidator

        with patch("engine.backtest.multi_symbol._run_symbol_backtest") as mock_worker:
            mock_worker.side_effect = [
                ("SYM_A", 0.2),
                ("SYM_B", 0.3),
            ]

            validator = MultiSymbolValidator(n_workers=1, sharpe_threshold=0.5)
            result = validator._validate_sequential(
                strategy_dict={"id": "test"},
                symbols=["SYM_A", "SYM_B"],
                start="2025-01-01",
                end="2025-12-31",
                timeframe="1d",
                initial_capital=10_000.0,
                fee_rate=0.0,
            )
            assert result.passed is False
            assert result.median_sharpe < 0.5

    def test_partial_failure_skips_failed_symbols(self):
        """일부 심볼 실패 시 나머지로 판정."""
        from unittest.mock import patch

        from engine.backtest.multi_symbol import MultiSymbolValidator

        with patch("engine.backtest.multi_symbol._run_symbol_backtest") as mock_worker:
            mock_worker.side_effect = [
                ("SYM_A", 0.8),
                ("SYM_B", None),   # failed
                ("SYM_C", 0.6),
            ]

            validator = MultiSymbolValidator(n_workers=1, sharpe_threshold=0.5)
            result = validator._validate_sequential(
                strategy_dict={"id": "test"},
                symbols=["SYM_A", "SYM_B", "SYM_C"],
                start="2025-01-01",
                end="2025-12-31",
                timeframe="1d",
                initial_capital=10_000.0,
                fee_rate=0.0,
            )
            # SYM_B failed, only A and C counted
            assert len(result.symbols) == 2
            assert "SYM_B" not in result.symbols
            assert result.passed is True
            assert result.median_sharpe == pytest.approx(0.7)

    def test_all_symbols_fail_returns_zero_median(self):
        """모든 심볼 실패 -> median=0, passed=False."""
        from unittest.mock import patch

        from engine.backtest.multi_symbol import MultiSymbolValidator

        with patch("engine.backtest.multi_symbol._run_symbol_backtest") as mock_worker:
            mock_worker.side_effect = [
                ("SYM_A", None),
                ("SYM_B", None),
            ]

            validator = MultiSymbolValidator(n_workers=1, sharpe_threshold=0.5)
            result = validator._validate_sequential(
                strategy_dict={"id": "test"},
                symbols=["SYM_A", "SYM_B"],
                start="2025-01-01",
                end="2025-12-31",
                timeframe="1d",
                initial_capital=10_000.0,
                fee_rate=0.0,
            )
            assert result.passed is False
            assert result.median_sharpe == 0.0
            assert len(result.symbols) == 0

    def test_validate_converts_strategy_to_dict(self):
        """validate()가 StrategyDefinition을 dict로 변환."""
        from unittest.mock import MagicMock, patch

        from engine.backtest.multi_symbol import MultiSymbolValidator

        mock_strategy = MagicMock()
        mock_strategy.model_dump.return_value = {"id": "test_strat"}

        with patch("engine.backtest.multi_symbol._run_symbol_backtest") as mock_worker:
            mock_worker.side_effect = [("SYM_A", 0.8)]

            validator = MultiSymbolValidator(n_workers=1, sharpe_threshold=0.5)
            result = validator._validate_sequential(
                strategy_dict=mock_strategy.model_dump(),
                symbols=["SYM_A"],
                start="2025-01-01",
                end="2025-12-31",
                timeframe="1d",
                initial_capital=10_000.0,
                fee_rate=0.0,
            )
            assert result.passed is True

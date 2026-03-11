"""Multi-symbol stability validation.

Correlation-based uncorrelated symbol selection + parallel backtest
+ median Sharpe gate for strategy robustness verification.

Usage:
    from engine.backtest.multi_symbol import MultiSymbolValidator
    validator = MultiSymbolValidator(n_workers=4, sharpe_threshold=0.5)
    result = validator.validate(strategy, symbols, "2025-01-01", "2025-12-31")
"""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MultiSymbolResult:
    """멀티심볼 백테스트 결과.

    Attributes:
        symbols: 테스트된 심볼 목록
        sharpe_per_symbol: 심볼별 Sharpe ratio
        median_sharpe: Sharpe 중앙값
        passed: median_sharpe >= threshold 여부
        threshold: 통과 기준 Sharpe
    """

    symbols: list[str]
    sharpe_per_symbol: dict[str, float]
    median_sharpe: float
    passed: bool
    threshold: float


# ---------------------------------------------------------------------------
# Symbol selection
# ---------------------------------------------------------------------------

def select_uncorrelated_symbols(
    symbols: list[str],
    returns_df: pd.DataFrame,
    max_corr: float = 0.5,
    n_select: int = 3,
) -> list[str]:
    """상관계수 기반 비상관 심볼 greedy 선택.

    Args:
        symbols: 후보 심볼 목록
        returns_df: 일간 수익률 DataFrame (columns = symbols)
        max_corr: 최대 허용 상관계수 (|r| < max_corr)
        n_select: 선택할 최대 심볼 수

    Returns:
        비상관 심볼 리스트 (최소 1개 — 첫 심볼은 항상 포함)
    """
    if not symbols:
        return []

    corr_matrix = returns_df[symbols].corr()
    selected = [symbols[0]]

    for sym in symbols[1:]:
        if len(selected) >= n_select:
            break
        is_uncorrelated = all(
            abs(corr_matrix.loc[sym, s]) < max_corr
            for s in selected
        )
        if is_uncorrelated:
            selected.append(sym)

    return selected


# ---------------------------------------------------------------------------
# Parallel backtest worker (top-level for pickle safety)
# ---------------------------------------------------------------------------

def _run_symbol_backtest(args: tuple) -> tuple[str, float | None]:
    """ProcessPoolExecutor용 top-level worker 함수.

    Args:
        args: (strategy_dict, symbol, start, end, timeframe, initial_capital, fee_rate)

    Returns:
        (symbol, sharpe) or (symbol, None) on failure.
    """
    strategy_dict, symbol, start, end, timeframe, initial_capital, fee_rate = args
    try:
        from engine.backtest.runner import BacktestRunner
        from engine.schema import StrategyDefinition

        strategy = StrategyDefinition.model_validate(strategy_dict)
        runner = BacktestRunner(fee_rate=fee_rate)
        result = runner.run(
            strategy, symbol, start, end,
            timeframe=timeframe, initial_capital=initial_capital,
        )
        return (symbol, result.sharpe_ratio)
    except Exception as exc:
        logger.debug("심볼 %s 백테스트 실패: %s", symbol, exc)
        return (symbol, None)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class MultiSymbolValidator:
    """멀티심볼 병렬 백테스트 + 중앙 Sharpe 게이트.

    ProcessPoolExecutor로 심볼별 백테스트를 병렬 실행하고,
    성공한 심볼들의 Sharpe 중앙값이 threshold 이상이면 통과.
    """

    def __init__(
        self,
        n_workers: int = 4,
        sharpe_threshold: float = 0.5,
    ) -> None:
        self._n_workers = n_workers
        self._sharpe_threshold = sharpe_threshold

    def validate(
        self,
        strategy,
        symbols: list[str],
        start: str,
        end: str,
        timeframe: str = "1d",
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.0,
    ) -> MultiSymbolResult:
        """심볼별 병렬 백테스트 실행 + 중앙 Sharpe 판정.

        Args:
            strategy: StrategyDefinition 또는 model_dump() dict
            symbols: 백테스트 대상 심볼 목록
            start: 시작일 "YYYY-MM-DD"
            end: 종료일 "YYYY-MM-DD"
            timeframe: 바 사이즈
            initial_capital: 초기 자본
            fee_rate: 수수료율

        Returns:
            MultiSymbolResult with per-symbol Sharpe and pass/fail.
        """
        # Ensure strategy is a dict for pickle safety
        if hasattr(strategy, "model_dump"):
            strategy_dict = strategy.model_dump()
        else:
            strategy_dict = dict(strategy)

        tasks = [
            (strategy_dict, sym, start, end, timeframe, initial_capital, fee_rate)
            for sym in symbols
        ]

        sharpe_per_symbol: dict[str, float] = {}

        logger.info(
            "멀티심볼 백테스트 시작: %d 심볼, %d workers",
            len(symbols), self._n_workers,
        )

        with ProcessPoolExecutor(max_workers=self._n_workers) as executor:
            futures = {
                executor.submit(_run_symbol_backtest, t): t[1]
                for t in tasks
            }
            for future in as_completed(futures):
                symbol = futures[future]
                sym, sharpe = future.result()
                if sharpe is not None:
                    sharpe_per_symbol[sym] = sharpe
                else:
                    logger.warning("심볼 %s 백테스트 실패 — skip", sym)

        # Compute median Sharpe from successful symbols
        if sharpe_per_symbol:
            sharpe_values = list(sharpe_per_symbol.values())
            median_sharpe = statistics.median(sharpe_values)
        else:
            median_sharpe = 0.0

        passed = median_sharpe >= self._sharpe_threshold

        logger.info(
            "멀티심볼 결과: %d/%d 성공, median Sharpe=%.3f, %s",
            len(sharpe_per_symbol), len(symbols),
            median_sharpe, "PASS" if passed else "FAIL",
        )

        return MultiSymbolResult(
            symbols=list(sharpe_per_symbol.keys()),
            sharpe_per_symbol=sharpe_per_symbol,
            median_sharpe=median_sharpe,
            passed=passed,
            threshold=self._sharpe_threshold,
        )

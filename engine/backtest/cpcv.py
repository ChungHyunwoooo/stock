"""Combinatorial Purged Cross-Validation 검증기 -- walk-forward와 동일 인터페이스."""

from __future__ import annotations

import numpy as np
import pandas as pd
from skfolio.model_selection import CombinatorialPurgedCV

from engine.backtest.metrics import compute_sharpe_ratio
from engine.backtest.validation_result import ValidationResult, WindowResult


class CPCVValidator:
    """CPCV 다중 경로 교차검증기.

    WalkForwardValidator와 동일한 ``validate(equity_curve) -> ValidationResult``
    시그니처를 제공하여 모드 전환만으로 사용 가능.

    Parameters
    ----------
    n_folds : int
        총 폴드 수 (default 6).
    n_test_folds : int
        테스트 폴드 수 (default 2). C(n_folds, n_test_folds) 경로 생성.
    purged_size : int
        train/test 경계에서 제거할 관측치 수 (default 10).
    embargo_size : int
        test 직후 train에서 제외할 관측치 수 (default 5).
    gap_threshold : float
        OOS Sharpe / IS Sharpe 최소 비율 (default 0.5).
    """

    def __init__(
        self,
        n_folds: int = 6,
        n_test_folds: int = 2,
        purged_size: int = 10,
        embargo_size: int = 5,
        gap_threshold: float = 0.5,
    ) -> None:
        self._n_folds = n_folds
        self._n_test_folds = n_test_folds
        self._purged_size = purged_size
        self._embargo_size = embargo_size
        self._gap_threshold = gap_threshold

    def validate(self, equity_curve: pd.Series) -> ValidationResult:
        """Equity curve에 CPCV 다중 경로 검증 수행.

        Parameters
        ----------
        equity_curve : pd.Series
            누적 자산 곡선 (예: [100, 101, 99, ...]).

        Returns
        -------
        ValidationResult
            mode="cpcv", 경로별 결과, overall 판정.

        Raises
        ------
        ValueError
            equity curve가 n_folds * 10 미만일 때.
        """
        n = len(equity_curve)
        min_required = self._n_folds * 10

        if n < min_required:
            raise ValueError(
                f"equity curve too short for {self._n_folds} folds "
                f"(got {n}, need >= {min_required})"
            )

        cv = CombinatorialPurgedCV(
            n_folds=self._n_folds,
            n_test_folds=self._n_test_folds,
            purged_size=self._purged_size,
            embargo_size=self._embargo_size,
        )

        # Equity curve를 numpy 2D array로 변환 (skfolio split 요구사항)
        X = equity_curve.values.reshape(-1, 1)

        windows: list[WindowResult] = []

        for i, (train_idx, test_groups) in enumerate(cv.split(X)):
            # train equity slice로 IS Sharpe 계산
            is_equity = equity_curve.iloc[train_idx]
            is_sharpe = compute_sharpe_ratio(is_equity) or 0.0

            # 각 test group을 합쳐 하나의 OOS 경로로 평가
            all_test_idx = np.concatenate(test_groups)
            all_test_idx.sort()
            oos_equity = equity_curve.iloc[all_test_idx]
            oos_sharpe = compute_sharpe_ratio(oos_equity) or 0.0

            if is_sharpe == 0:
                gap_ratio = 0.0
            else:
                raw = oos_sharpe / is_sharpe
                # Negative ratio (opposite sign) → 0으로 클램핑
                gap_ratio = max(raw, 0.0)

            passed = gap_ratio >= self._gap_threshold

            windows.append(
                WindowResult(
                    window_idx=i,
                    is_sharpe=is_sharpe,
                    oos_sharpe=oos_sharpe,
                    gap_ratio=gap_ratio,
                    passed=passed,
                )
            )

        n_passed = sum(1 for w in windows if w.passed)
        pass_rate = n_passed / len(windows) if windows else 0.0

        return ValidationResult(
            mode="cpcv",
            windows=windows,
            overall_passed=pass_rate >= 0.5,
            summary={
                "n_paths": len(windows),
                "pass_rate": pass_rate,
                "gap_threshold": self._gap_threshold,
                "passed_count": n_passed,
                "failed_count": len(windows) - n_passed,
            },
        )

"""Walk-forward OOS 검증기 -- IS/OOS 분할 + 성과 갭 임계치 판정."""

from __future__ import annotations

import pandas as pd

from engine.backtest.metrics import compute_sharpe_ratio
from engine.backtest.validation_result import ValidationResult, WindowResult


class WalkForwardValidator:
    """Equity curve를 n개 윈도우로 분할하여 IS/OOS Sharpe 갭을 판정한다.

    Parameters
    ----------
    n_windows : int
        분할 윈도우 수 (default 5, CONTEXT.md locked).
    train_pct : float
        각 윈도우에서 IS(훈련) 비율 (default 0.7 = 70%, CONTEXT.md locked).
    gap_threshold : float
        OOS Sharpe / IS Sharpe 최소 비율 (default 0.5, CONTEXT.md locked).
    """

    def __init__(
        self,
        n_windows: int = 5,
        train_pct: float = 0.7,
        gap_threshold: float = 0.5,
    ) -> None:
        self._n_windows = n_windows
        self._train_pct = train_pct
        self._gap_threshold = gap_threshold

    def validate(self, equity_curve: pd.Series) -> ValidationResult:
        """Equity curve를 n_windows로 분할하여 IS/OOS 성과 갭 검증.

        Parameters
        ----------
        equity_curve : pd.Series
            누적 자산 곡선 (예: [100, 101, 99, ...]).

        Returns
        -------
        ValidationResult
            mode="walk_forward", 윈도우별 결과, overall 판정.

        Raises
        ------
        ValueError
            equity curve가 n_windows * 10 미만일 때.
        """
        n = len(equity_curve)
        min_required = self._n_windows * 10

        if n < min_required:
            raise ValueError(
                f"equity curve too short for {self._n_windows} windows "
                f"(got {n}, need >= {min_required})"
            )

        window_size = n // self._n_windows
        train_size = int(window_size * self._train_pct)

        windows: list[WindowResult] = []

        for i in range(self._n_windows):
            start = i * window_size
            train_end = start + train_size
            window_end = start + window_size

            is_slice = equity_curve.iloc[start:train_end]
            oos_slice = equity_curve.iloc[train_end:window_end]

            is_sharpe = compute_sharpe_ratio(is_slice) or 0.0
            oos_sharpe = compute_sharpe_ratio(oos_slice) or 0.0

            if is_sharpe == 0:
                gap_ratio = 0.0
            else:
                raw = oos_sharpe / is_sharpe
                # Negative ratio (opposite sign) is meaningless -- clamp to 0
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

        overall_passed = all(w.passed for w in windows)

        return ValidationResult(
            mode="walk_forward",
            windows=windows,
            overall_passed=overall_passed,
            summary={
                "n_windows": len(windows),
                "gap_threshold": self._gap_threshold,
                "passed_count": sum(1 for w in windows if w.passed),
                "failed_count": sum(1 for w in windows if not w.passed),
            },
        )

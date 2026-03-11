"""Walk-forward / CPCV 검증 결과 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WindowResult:
    """단일 윈도우 IS/OOS 결과."""

    window_idx: int
    is_sharpe: float
    oos_sharpe: float
    gap_ratio: float  # oos_sharpe / is_sharpe
    passed: bool  # gap_ratio >= threshold


@dataclass(slots=True)
class ValidationResult:
    """WF 또는 CPCV 검증 결과."""

    mode: str  # "walk_forward" | "cpcv"
    windows: list[WindowResult]
    overall_passed: bool
    summary: dict  # 통계 요약

"""인디케이터 공통 타입 및 유틸."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd


Array = np.ndarray | pd.Series


class SingleResult(NamedTuple):
    """단일 출력 인디케이터 결과."""
    values: np.ndarray
    current: float

    @staticmethod
    def from_array(arr: np.ndarray) -> SingleResult:
        last = float(arr[-1]) if len(arr) > 0 and not np.isnan(arr[-1]) else float("nan")
        return SingleResult(values=arr, current=last)


class BandResult(NamedTuple):
    """밴드형 인디케이터 결과 (upper/middle/lower)."""
    upper: np.ndarray
    middle: np.ndarray
    lower: np.ndarray
    current_upper: float
    current_middle: float
    current_lower: float

    @staticmethod
    def from_arrays(upper: np.ndarray, middle: np.ndarray, lower: np.ndarray) -> BandResult:
        def last(arr: np.ndarray) -> float:
            return float(arr[-1]) if len(arr) > 0 and not np.isnan(arr[-1]) else float("nan")
        return BandResult(
            upper=upper, middle=middle, lower=lower,
            current_upper=last(upper), current_middle=last(middle), current_lower=last(lower),
        )


class DualResult(NamedTuple):
    """2개 출력 인디케이터 결과."""
    line: np.ndarray
    signal: np.ndarray
    current_line: float
    current_signal: float

    @staticmethod
    def from_arrays(line: np.ndarray, signal: np.ndarray) -> DualResult:
        def last(arr: np.ndarray) -> float:
            return float(arr[-1]) if len(arr) > 0 and not np.isnan(arr[-1]) else float("nan")
        return DualResult(
            line=line, signal=signal,
            current_line=last(line), current_signal=last(signal),
        )


class TripleResult(NamedTuple):
    """3개 출력 인디케이터 결과 (MACD 등)."""
    line: np.ndarray
    signal: np.ndarray
    histogram: np.ndarray
    current_line: float
    current_signal: float
    current_histogram: float

    @staticmethod
    def from_arrays(line: np.ndarray, signal: np.ndarray, histogram: np.ndarray) -> TripleResult:
        def last(arr: np.ndarray) -> float:
            return float(arr[-1]) if len(arr) > 0 and not np.isnan(arr[-1]) else float("nan")
        return TripleResult(
            line=line, signal=signal, histogram=histogram,
            current_line=last(line), current_signal=last(signal), current_histogram=last(histogram),
        )


def _to_numpy(data: Array) -> np.ndarray:
    """pd.Series → np.ndarray 변환."""
    if isinstance(data, pd.Series):
        return data.values.astype(float)
    return np.asarray(data, dtype=float)

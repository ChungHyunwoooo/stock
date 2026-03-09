"""볼린저 밴드 컨텍스트 — BB 위치, 스퀴즈, %B.

의존성: talib, numpy
성능: ~1ms
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def calc_bb_position(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict:
    """볼린저 밴드 컨텍스트 분석.

    밴드폭, %B, 스퀴즈/확장 감지.

    Returns:
        {
            upper: float,
            middle: float,
            lower: float,
            bandwidth: float,    # (상단-하단)/중단 × 100
            pct_b: float,        # (종가-하단)/(상단-하단), 0=하단 1=상단
            is_squeeze: bool,    # 밴드폭 < 20봉 최소 × 1.1
            is_expansion: bool,  # 밴드폭 > 20봉 평균 × 1.5
        }
    """
    result = {
        "upper": 0.0,
        "middle": 0.0,
        "lower": 0.0,
        "bandwidth": 0.0,
        "pct_b": 0.5,
        "is_squeeze": False,
        "is_expansion": False,
    }

    if len(df) < period + 20:
        return result

    close = df["close"].values

    upper, middle, lower = talib.BBANDS(
        close, timeperiod=period, nbdevup=std, nbdevdn=std, matype=0
    )

    if np.isnan(upper[-1]) or np.isnan(middle[-1]) or np.isnan(lower[-1]):
        return result

    curr_upper = float(upper[-1])
    curr_middle = float(middle[-1])
    curr_lower = float(lower[-1])
    curr_close = float(close[-1])

    result["upper"] = curr_upper
    result["middle"] = curr_middle
    result["lower"] = curr_lower

    # Bandwidth
    if curr_middle > 0:
        result["bandwidth"] = round((curr_upper - curr_lower) / curr_middle * 100, 4)

    # %B
    band_range = curr_upper - curr_lower
    if band_range > 0:
        result["pct_b"] = round((curr_close - curr_lower) / band_range, 4)

    # 스퀴즈/확장 판단 (최근 20봉 밴드폭 기준)
    bandwidths = []
    for i in range(-20, 0):
        idx = len(upper) + i
        if idx >= 0 and not np.isnan(upper[idx]) and not np.isnan(lower[idx]) and not np.isnan(middle[idx]):
            m = float(middle[idx])
            if m > 0:
                bw = (float(upper[idx]) - float(lower[idx])) / m * 100
                bandwidths.append(bw)

    if bandwidths:
        bw_min = min(bandwidths)
        bw_avg = sum(bandwidths) / len(bandwidths)
        result["is_squeeze"] = result["bandwidth"] < bw_min * 1.1
        result["is_expansion"] = result["bandwidth"] > bw_avg * 1.5

    return result

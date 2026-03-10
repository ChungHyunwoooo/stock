"""ADX 추세 강도 필터 — ADX + DI 추세 방향/강도.

의존성: talib, numpy
성능: ~2ms
"""

import numpy as np
import pandas as pd
import talib

def calc_adx_filter(df: pd.DataFrame, period: int = 14) -> dict:
    """ADX + DI 추세 강도 필터.

    ADX > 20 = 추세장, ADX > 25 = 강한 추세, ADX < 20 = 횡보.
    DI+ vs DI- → 방향성.

    Returns:
        {
            adx: float,
            plus_di: float,
            minus_di: float,
            is_trending: bool,      # ADX > 20
            is_strong_trend: bool,  # ADX > 25
            trend_direction: str,   # "BULLISH" | "BEARISH" | "NEUTRAL"
            di_spread: float,       # abs(DI+ - DI-)
        }
    """
    result = {
        "adx": 0.0,
        "plus_di": 0.0,
        "minus_di": 0.0,
        "is_trending": False,
        "is_strong_trend": False,
        "trend_direction": "NEUTRAL",
        "di_spread": 0.0,
    }

    if len(df) < period * 2:
        return result

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    adx = talib.ADX(high, low, close, timeperiod=period)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=period)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=period)

    if np.isnan(adx[-1]) or np.isnan(plus_di[-1]) or np.isnan(minus_di[-1]):
        return result

    curr_adx = float(adx[-1])
    curr_plus = float(plus_di[-1])
    curr_minus = float(minus_di[-1])

    result["adx"] = round(curr_adx, 2)
    result["plus_di"] = round(curr_plus, 2)
    result["minus_di"] = round(curr_minus, 2)
    result["is_trending"] = curr_adx > 20
    result["is_strong_trend"] = curr_adx > 25
    result["di_spread"] = round(abs(curr_plus - curr_minus), 2)

    if curr_plus > curr_minus:
        result["trend_direction"] = "BULLISH"
    elif curr_minus > curr_plus:
        result["trend_direction"] = "BEARISH"
    else:
        result["trend_direction"] = "NEUTRAL"

    return result

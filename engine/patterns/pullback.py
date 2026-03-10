"""EMA 되돌림 품질 분석.

의존성: talib, pandas
성능: ~0.5ms
"""

import numpy as np
import pandas as pd
import talib

def calc_pullback_quality(df: pd.DataFrame, ema_period: int = 21) -> dict:
    """EMA 되돌림 품질 분석.

    최근 3봉 내 저가가 EMA를 터치 또는 관통했는지,
    되돌림 깊이 및 바운스 확인.

    Returns:
        {
            is_pullback_to_ema: bool,     # EMA 터치/관통 여부
            pullback_depth_pct: float,    # 최근 스윙 고점 대비 되돌림 %
            bounce_confirmed: bool,       # EMA 터치 후 양봉/핀바 출현
            bars_since_touch: int,        # EMA 터치 후 경과 봉수 (0 = 현재봉)
        }
    """
    result = {
        "is_pullback_to_ema": False,
        "pullback_depth_pct": 0.0,
        "bounce_confirmed": False,
        "bars_since_touch": -1,
    }

    if len(df) < ema_period + 10:
        return result

    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    opens = df["open"].values

    ema = talib.EMA(close, timeperiod=ema_period)
    if np.isnan(ema[-1]):
        return result

    # 최근 3봉 내 EMA 터치/관통 확인
    touch_threshold = 0.003  # EMA 대비 0.3% 이내 = 터치
    bars_since = -1

    for i in range(1, 4):  # -1, -2, -3 (최근 3봉)
        idx = -i
        if abs(len(close) + idx) >= len(ema) or np.isnan(ema[idx]):
            continue
        ema_val = float(ema[idx])
        bar_low = float(low[idx])

        # 저가가 EMA를 터치 (위에서 내려와서 EMA 근처) 또는 관통
        if bar_low <= ema_val * (1 + touch_threshold):
            result["is_pullback_to_ema"] = True
            bars_since = i - 1
            break

    result["bars_since_touch"] = bars_since

    # 되돌림 깊이: 최근 스윙 고점 대비 %
    lookback = min(20, len(high))
    recent_high = float(np.max(high[-lookback:]))
    curr_close = float(close[-1])

    if recent_high > 0:
        result["pullback_depth_pct"] = round(
            (recent_high - curr_close) / recent_high * 100, 2
        )

    # 바운스 확인: EMA 터치 이후 양봉 또는 핀바 출현
    if result["is_pullback_to_ema"]:
        curr_open = float(opens[-1])
        curr_close_val = float(close[-1])
        curr_low_val = float(low[-1])
        curr_high_val = float(high[-1])

        is_bullish = curr_close_val > curr_open
        body = abs(curr_close_val - curr_open)
        lower_wick = min(curr_open, curr_close_val) - curr_low_val
        full_range = curr_high_val - curr_low_val

        # 핀바 (긴 아래꼬리)
        is_pin = (lower_wick > body * 2 and body < full_range * 0.3) if full_range > 0 else False

        result["bounce_confirmed"] = is_bullish or is_pin

    return result

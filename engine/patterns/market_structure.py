"""시장 구조 분석 — HH/HL/LH/LL, BOS, 추세 판별.

5-bar 피봇 기반 스윙 고점/저점 감지 후 시장 구조 판별.
의존성: numpy, pandas (talib 불필요)
성능: ~1ms
"""

import pandas as pd

def detect_market_structure(df: pd.DataFrame, lookback: int = 50) -> dict:
    """시장 구조 분석.

    5-bar 피봇으로 스윙 고점/저점을 감지하고,
    연속 HH/HL → BULLISH, LH/LL → BEARISH, 혼합 → RANGING 판별.

    Returns:
        {
            trend: "BULLISH" | "BEARISH" | "RANGING",
            last_swing_high: float,
            last_swing_low: float,
            bos_bullish: bool,   # 종가가 직전 스윙 고점 돌파
            bos_bearish: bool,   # 종가가 직전 스윙 저점 이탈
            hh_count: int,       # 연속 Higher High 수
            hl_count: int,       # 연속 Higher Low 수
        }
    """
    result = {
        "trend": "RANGING",
        "last_swing_high": 0.0,
        "last_swing_low": 0.0,
        "bos_bullish": False,
        "bos_bearish": False,
        "hh_count": 0,
        "hl_count": 0,
    }

    if len(df) < lookback:
        return result

    high = df["high"].values[-lookback:]
    low = df["low"].values[-lookback:]
    close = df["close"].values[-lookback:]

    # 5-bar pivot detection
    swing_highs = []  # (index, price)
    swing_lows = []   # (index, price)

    for i in range(2, len(high) - 2):
        # Swing high: higher than 2 bars on each side
        if (high[i] > high[i - 1] and high[i] > high[i - 2]
                and high[i] > high[i + 1] and high[i] > high[i + 2]):
            swing_highs.append((i, float(high[i])))

        # Swing low: lower than 2 bars on each side
        if (low[i] < low[i - 1] and low[i] < low[i - 2]
                and low[i] < low[i + 1] and low[i] < low[i + 2]):
            swing_lows.append((i, float(low[i])))

    if not swing_highs or not swing_lows:
        return result

    # Last swing high/low
    result["last_swing_high"] = swing_highs[-1][1]
    result["last_swing_low"] = swing_lows[-1][1]

    curr_close = float(close[-1])

    # BOS detection
    result["bos_bullish"] = curr_close > swing_highs[-1][1]
    result["bos_bearish"] = curr_close < swing_lows[-1][1]

    # Count consecutive HH/HL and LH/LL
    hh_count = 0
    hl_count = 0
    lh_count = 0
    ll_count = 0

    # Higher Highs
    for i in range(len(swing_highs) - 1, 0, -1):
        if swing_highs[i][1] > swing_highs[i - 1][1]:
            hh_count += 1
        else:
            break

    # Higher Lows
    for i in range(len(swing_lows) - 1, 0, -1):
        if swing_lows[i][1] > swing_lows[i - 1][1]:
            hl_count += 1
        else:
            break

    # Lower Highs
    for i in range(len(swing_highs) - 1, 0, -1):
        if swing_highs[i][1] < swing_highs[i - 1][1]:
            lh_count += 1
        else:
            break

    # Lower Lows
    for i in range(len(swing_lows) - 1, 0, -1):
        if swing_lows[i][1] < swing_lows[i - 1][1]:
            ll_count += 1
        else:
            break

    result["hh_count"] = hh_count
    result["hl_count"] = hl_count

    # Trend determination
    if hh_count >= 2 and hl_count >= 2:
        result["trend"] = "BULLISH"
    elif lh_count >= 2 and ll_count >= 2:
        result["trend"] = "BEARISH"
    else:
        result["trend"] = "RANGING"

    return result

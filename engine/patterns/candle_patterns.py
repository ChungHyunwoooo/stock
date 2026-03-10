"""캔들 패턴 인식 — 장악형, 핀바, 내포봉.

의존성: pandas (talib 불필요)
성능: ~0.1ms
"""

import pandas as pd

def detect_candle_pattern(df: pd.DataFrame) -> dict:
    """최근 2봉 기반 캔들 패턴 인식.

    Returns:
        {
            bullish_engulfing: bool,
            bearish_engulfing: bool,
            bullish_pin_bar: bool,
            bearish_pin_bar: bool,
            inside_bar: bool,
            pattern_strength: float,  # 0.0 - 1.0
        }
    """
    result = {
        "bullish_engulfing": False,
        "bearish_engulfing": False,
        "bullish_pin_bar": False,
        "bearish_pin_bar": False,
        "inside_bar": False,
        "pattern_strength": 0.0,
    }

    if len(df) < 3:
        return result

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    c_open, c_close = float(curr["open"]), float(curr["close"])
    c_high, c_low = float(curr["high"]), float(curr["low"])
    p_open, p_close = float(prev["open"]), float(prev["close"])
    p_high, p_low = float(prev["high"]), float(prev["low"])

    c_body = abs(c_close - c_open)
    p_body = abs(p_close - p_open)
    c_range = c_high - c_low
    p_range = p_high - p_low

    if c_range == 0 or p_range == 0:
        return result

    c_upper_wick = c_high - max(c_open, c_close)
    c_lower_wick = min(c_open, c_close) - c_low

    strength = 0.0

    # --- 장악형 (Engulfing) ---
    # Bullish: 이전 음봉 몸통을 현재 양봉이 완전 감싸기
    if (p_close < p_open  # prev bearish
            and c_close > c_open  # curr bullish
            and c_close > p_open  # curr close above prev open
            and c_open < p_close):  # curr open below prev close
        result["bullish_engulfing"] = True
        # strength: 감싸기 비율
        strength = max(strength, min(1.0, c_body / p_body * 0.5) if p_body > 0 else 0.5)

    # Bearish: 이전 양봉 몸통을 현재 음봉이 완전 감싸기
    if (p_close > p_open  # prev bullish
            and c_close < c_open  # curr bearish
            and c_open > p_close  # curr open above prev close
            and c_close < p_open):  # curr close below prev open
        result["bearish_engulfing"] = True
        strength = max(strength, min(1.0, c_body / p_body * 0.5) if p_body > 0 else 0.5)

    # --- 핀바 (Pin Bar) ---
    # 꼬리 > 몸통×2, 몸통 < 전체범위 30%
    body_ratio = c_body / c_range if c_range > 0 else 1.0

    # Bullish pin bar: 긴 아래꼬리 (망치형)
    if (c_lower_wick > c_body * 2
            and body_ratio < 0.30
            and c_upper_wick < c_lower_wick * 0.3):
        result["bullish_pin_bar"] = True
        strength = max(strength, min(1.0, c_lower_wick / c_range))

    # Bearish pin bar: 긴 위꼬리 (유성형)
    if (c_upper_wick > c_body * 2
            and body_ratio < 0.30
            and c_lower_wick < c_upper_wick * 0.3):
        result["bearish_pin_bar"] = True
        strength = max(strength, min(1.0, c_upper_wick / c_range))

    # --- 내포봉 (Inside Bar) ---
    # 현재봉 고저가 이전봉 안에 포함
    if c_high <= p_high and c_low >= p_low:
        result["inside_bar"] = True
        # Inside bar strength: 얼마나 작은지 (작을수록 폭발 가능성↑)
        if p_range > 0:
            strength = max(strength, min(1.0, 1.0 - c_range / p_range))

    result["pattern_strength"] = round(strength, 3)
    return result

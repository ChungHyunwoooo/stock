"""지지/저항 레벨 감지 — 스윙 클러스터링, 라운드넘버.

의존성: numpy, pandas
성능: ~2ms
"""

import numpy as np
import pandas as pd

# KRW 라운드넘버 기준점
_ROUND_NUMBERS = [
    100, 500, 1_000, 5_000, 10_000, 50_000, 100_000,
    500_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000,
    100_000_000,
]

def detect_key_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
    """지지/저항 레벨 감지.

    스윙 고점/저점을 변동성 적응형 임계값으로 클러스터링하여 레벨 존 생성.
    터치 횟수로 레벨 강도 판단. 횡보장 보호 포함.

    Returns:
        {
            nearest_support: float,
            nearest_resistance: float,
            at_support: bool,       # 현재가가 지지선 근처
            at_resistance: bool,    # 현재가가 저항선 근처
            support_touches: int,
            resistance_touches: int,
            round_number_near: bool,
        }
    """
    result = {
        "nearest_support": 0.0,
        "nearest_resistance": 0.0,
        "at_support": False,
        "at_resistance": False,
        "support_touches": 0,
        "resistance_touches": 0,
        "round_number_near": False,
    }

    if len(df) < 20:
        return result

    high = df["high"].values[-lookback:]
    low = df["low"].values[-lookback:]
    close = df["close"].values[-lookback:]
    curr_close = float(close[-1])

    if curr_close <= 0:
        return result

    # 변동성 기반 적응형 임계값 (ATR 대용: 최근 20봉 고저 평균 범위)
    recent_n = min(20, len(high))
    avg_range = float(np.mean(high[-recent_n:] - low[-recent_n:]))
    volatility_pct = avg_range / curr_close if curr_close > 0 else 0.005

    # 클러스터링 임계값: 변동성의 1.5배, 최소 0.3%, 최대 1.5%
    threshold = max(0.003, min(0.015, volatility_pct * 1.5))

    # 5-bar 피봇으로 스윙 고점/저점 분리 수집
    swing_highs = []
    swing_lows = []
    for i in range(2, len(high) - 2):
        # Swing high
        if (high[i] > high[i - 1] and high[i] > high[i - 2]
                and high[i] > high[i + 1] and high[i] > high[i + 2]):
            swing_highs.append(float(high[i]))
        # Swing low
        if (low[i] < low[i - 1] and low[i] < low[i - 2]
                and low[i] < low[i + 1] and low[i] < low[i + 2]):
            swing_lows.append(float(low[i]))

    # 스윙 포인트가 너무 적으면 3-bar 피봇으로 보완
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        for i in range(1, len(high) - 1):
            if (high[i] > high[i - 1] and high[i] > high[i + 1]):
                val = float(high[i])
                if val not in swing_highs:
                    swing_highs.append(val)
            if (low[i] < low[i - 1] and low[i] < low[i + 1]):
                val = float(low[i])
                if val not in swing_lows:
                    swing_lows.append(val)

    all_swings = swing_highs + swing_lows
    if not all_swings:
        return result

    # 클러스터링
    all_swings.sort()
    clusters = []
    current_cluster = [all_swings[0]]

    for i in range(1, len(all_swings)):
        if abs(all_swings[i] - current_cluster[-1]) / current_cluster[-1] < threshold:
            current_cluster.append(all_swings[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [all_swings[i]]
    clusters.append(current_cluster)

    # 클러스터 평균가와 터치 횟수 (최대 10으로 캡)
    levels = []
    for cluster in clusters:
        avg_price = sum(cluster) / len(cluster)
        touches = min(len(cluster), 10)
        levels.append((avg_price, touches))

    # 현재가 기준 지지/저항 분류 (현재가와 같은 레벨은 무시)
    min_gap = curr_close * 0.001  # 0.1% 미만 차이는 '같은 가격'으로 간주
    supports = [(p, t) for p, t in levels if curr_close - p > min_gap]
    resistances = [(p, t) for p, t in levels if p - curr_close > min_gap]

    proximity = curr_close * threshold  # 근접 판단도 변동성 기반

    if supports:
        supports.sort(key=lambda x: curr_close - x[0])
        nearest_sup, sup_touches = supports[0]
        result["nearest_support"] = nearest_sup
        result["support_touches"] = sup_touches
        result["at_support"] = (curr_close - nearest_sup) < proximity
    else:
        # 폴백: 스윙 로우가 있으면 최근 최저가를 지지로 사용
        if swing_lows:
            fallback_sup = max(s for s in swing_lows if s < curr_close) if any(s < curr_close for s in swing_lows) else 0.0
            if fallback_sup > 0:
                result["nearest_support"] = fallback_sup
                result["support_touches"] = 1

    if resistances:
        resistances.sort(key=lambda x: x[0] - curr_close)
        nearest_res, res_touches = resistances[0]
        result["nearest_resistance"] = nearest_res
        result["resistance_touches"] = res_touches
        result["at_resistance"] = (nearest_res - curr_close) < proximity
    else:
        # 폴백: 스윙 하이가 있으면 최근 최고가를 저항으로 사용
        if swing_highs:
            fallback_res = min(s for s in swing_highs if s > curr_close) if any(s > curr_close for s in swing_highs) else 0.0
            if fallback_res > 0:
                result["nearest_resistance"] = fallback_res
                result["resistance_touches"] = 1

    # 라운드넘버 근접 확인
    for rn in _ROUND_NUMBERS:
        if abs(curr_close - rn) / curr_close < 0.005:
            result["round_number_near"] = True
            break

    return result

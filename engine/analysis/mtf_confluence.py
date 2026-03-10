"""멀티타임프레임 컨플루언스 분석.

상위 TF 트렌드 방향 확인 → 하위 TF 진입 시점 포착.
D1 트렌드 + 4H 구조 + 1H/15m 진입.
"""

import pandas as pd

from engine.patterns.market_structure import detect_market_structure
from engine.patterns.trend_strength import calc_adx_filter

# TF 가중치 정의
_TF_WEIGHTS: dict[str, float] = {
    "1d": 0.40,
    "4h": 0.35,
    "1h": 0.25,
}

_DEFAULT_RESULT: dict = {
    "score": 0.0,
    "aligned_count": 0,
    "total_tfs": 0,
    "details": {},
    "d1_trend": "RANGING",
    "h4_structure": "RANGING",
    "h1_trigger": False,
}

def _score_trend(trend: str, side: str) -> float:
    """트렌드 방향과 진입 방향 일치도 점수 반환."""
    if side == "LONG":
        return {"BULLISH": 1.0, "RANGING": 0.3, "BEARISH": 0.0}.get(trend, 0.0)
    else:  # SHORT
        return {"BEARISH": 1.0, "RANGING": 0.3, "BULLISH": 0.0}.get(trend, 0.0)

def _calc_ema21(series: pd.Series) -> pd.Series:
    """EMA21 계산 (pandas ewm, talib 미사용)."""
    return series.ewm(span=21, adjust=False).mean()

def _check_h1_trigger(df: pd.DataFrame, side: str) -> bool:
    """1H 트리거 조건 확인.

    LONG: 최근 3봉 중 저점이 상승(higher low) + 종가가 EMA21 위
    SHORT: 최근 3봉 중 고점이 하락(lower high) + 종가가 EMA21 아래
    """
    if len(df) < 22:  # EMA21 계산에 최소 22봉 필요
        return False

    ema21 = _calc_ema21(df["close"])
    curr_close = float(df["close"].iloc[-1])
    curr_ema = float(ema21.iloc[-1])

    recent_lows = df["low"].iloc[-3:].values
    recent_highs = df["high"].iloc[-3:].values

    if side == "LONG":
        higher_low = (recent_lows[-1] > recent_lows[-2]) and (recent_lows[-2] > recent_lows[-3])
        above_ema = curr_close > curr_ema
        return higher_low and above_ema
    else:  # SHORT
        lower_high = (recent_highs[-1] < recent_highs[-2]) and (recent_highs[-2] < recent_highs[-3])
        below_ema = curr_close < curr_ema
        return lower_high and below_ema

def calc_mtf_confluence(
    frames: dict[str, pd.DataFrame],
    side: str,
) -> dict:
    """멀티타임프레임 컨플루언스 점수 계산.

    Args:
        frames: {"1d": df_daily, "4h": df_4h, "1h": df_1h, ...} TF별 OHLCV
        side: "LONG" or "SHORT"

    Returns:
        {
            "score": float,          # 0.0 ~ 1.0 정규화 점수
            "aligned_count": int,    # 정렬된 TF 수
            "total_tfs": int,        # 분석된 총 TF 수
            "details": dict,         # TF별 상세 {tf: {"trend": str, "adx": float, "aligned": bool}}
            "d1_trend": str,         # D1 트렌드
            "h4_structure": str,     # 4H 구조
            "h1_trigger": bool,      # 1H 트리거 발생 여부
        }
    """
    if not frames:
        return dict(_DEFAULT_RESULT)

    details: dict = {}
    weighted_score = 0.0
    weight_sum = 0.0
    aligned_count = 0

    d1_trend = "RANGING"
    h4_structure = "RANGING"
    h1_trigger = False

    # 분석할 TF 목록: 가중치 정의된 TF만 처리 (순서 유지)
    for tf, weight in _TF_WEIGHTS.items():
        df = frames.get(tf)
        if df is None or df.empty:
            continue

        # 시장 구조 분석
        ms = detect_market_structure(df)
        trend = ms["trend"]

        # ADX 분석
        adx_result = calc_adx_filter(df)
        adx_val = adx_result["adx"]

        # TF별 특수 처리
        if tf == "1h":
            # 1H: 트리거 조건 확인
            trigger = _check_h1_trigger(df, side)
            h1_trigger = trigger

            # ADX 보너스: ADX > 20이면 트리거 점수에 0.1 가산
            tf_score = _score_trend(trend, side)
            if trigger:
                tf_score = min(1.0, tf_score + (0.1 if adx_val > 20 else 0.0))
            aligned = trigger
        else:
            tf_score = _score_trend(trend, side)
            aligned = tf_score >= 0.5  # 0.5 이상이면 정렬된 것으로 판단

            # 4H BOS 추가 확인
            if tf == "4h":
                if side == "LONG" and ms.get("bos_bullish"):
                    tf_score = min(1.0, tf_score + 0.1)
                elif side == "SHORT" and ms.get("bos_bearish"):
                    tf_score = min(1.0, tf_score + 0.1)

        # TF별 트렌드 저장
        if tf == "1d":
            d1_trend = trend
        elif tf == "4h":
            h4_structure = trend

        # 정렬 카운트
        if tf == "1h":
            if h1_trigger:
                aligned_count += 1
        elif aligned:
            aligned_count += 1

        details[tf] = {
            "trend": trend,
            "adx": adx_val,
            "aligned": aligned if tf != "1h" else h1_trigger,
        }

        weighted_score += tf_score * weight
        weight_sum += weight

    if weight_sum == 0.0:
        return dict(_DEFAULT_RESULT)

    # 정규화: 실제 분석된 TF 가중치 합으로 나눔
    final_score = round(weighted_score / weight_sum, 4)

    return {
        "score": final_score,
        "aligned_count": aligned_count,
        "total_tfs": len(details),
        "details": details,
        "d1_trend": d1_trend,
        "h4_structure": h4_structure,
        "h1_trigger": h1_trigger,
    }

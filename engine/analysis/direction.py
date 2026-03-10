"""방향 판단 — BULL / BEAR / NEUTRAL 최종 판정.

indicators + patterns 결과를 종합하여 방향과 신뢰도를 산출.
기존 confidence.py 로직을 흡수.
"""

from __future__ import annotations


def judge_direction(
    base: float,
    adx: dict,
    volume: dict,
    structure: dict,
    candle: dict,
    key_levels: dict,
    side: str,
) -> dict:
    """BULL / BEAR / NEUTRAL 최종 판단.

    가중치 배분:
    - 기본 시그널 품질: 20% (전략별 base 값)
    - 추세 정렬: 30% (ADX 강도 × 구조 방향 일치)
    - 거래량 확인: 20% (비율 + OBV + 다이버전스 없음)
    - 키레벨 컨플루언스: 15% (LONG=지지선, SHORT=저항선)
    - 캔들 패턴: 15% (장악형/핀바 출현 × strength)

    Returns:
        {
            "direction": "BULL" | "BEAR" | "NEUTRAL",
            "confidence": 0.0~1.0,
            "breakdown": "시그널20% + 추세30% + ...",
            "reasons": ["ADX 강한 추세", "OBV 상승", ...],
        }
    """
    score = 0.0
    reasons: list[str] = []

    # --- 1. 기본 시그널 품질 (20%) ---
    base_score = min(1.0, max(0.0, base))
    score += base_score * 0.20

    # --- 2. 추세 정렬 (30%) ---
    adx_val = adx.get("adx", 0)
    if adx_val > 25:
        adx_strength = 1.0
        reasons.append("ADX 강한 추세")
    elif adx_val > 20:
        adx_strength = 0.7
        reasons.append("ADX 추세 진행")
    elif adx_val > 15:
        adx_strength = 0.3
    else:
        adx_strength = 0.0

    trend = structure.get("trend", "RANGING")
    if side == "LONG":
        direction_match = {"BULLISH": 1.0, "RANGING": 0.4, "BEARISH": 0.0}.get(trend, 0.0)
    else:
        direction_match = {"BEARISH": 1.0, "RANGING": 0.4, "BULLISH": 0.0}.get(trend, 0.0)

    if direction_match >= 1.0:
        reasons.append(f"구조 {trend} 정렬")

    di_bonus = 0.0
    trend_dir = adx.get("trend_direction", "NEUTRAL")
    if (side == "LONG" and trend_dir == "BULLISH") or (side == "SHORT" and trend_dir == "BEARISH"):
        di_bonus = 0.2
        reasons.append(f"DI {trend_dir} 일치")

    trend_score = adx_strength * 0.4 + direction_match * 0.4 + di_bonus
    score += min(1.0, trend_score) * 0.30

    # --- 3. 거래량 확인 (20%) ---
    vol_score = 0.0
    vol_ratio = volume.get("vol_ratio", 0)
    if vol_ratio >= 2.0:
        vol_score += 0.4
        reasons.append(f"거래량 {vol_ratio}x 급증")
    elif vol_ratio >= 1.5:
        vol_score += 0.3
    elif vol_ratio >= 1.2:
        vol_score += 0.2

    obv_trend = volume.get("obv_trend", "FLAT")
    if (side == "LONG" and obv_trend == "RISING") or (side == "SHORT" and obv_trend == "FALLING"):
        vol_score += 0.3
        reasons.append(f"OBV {obv_trend}")

    if not volume.get("vol_price_divergence", False):
        vol_score += 0.2
    else:
        reasons.append("거래량 다이버전스 경고")

    if volume.get("is_climactic", False):
        vol_score -= 0.3
        reasons.append("클라이맥스 거래량 경고")

    score += max(0.0, min(1.0, vol_score)) * 0.20

    # --- 4. 키레벨 컨플루언스 (15%) ---
    level_score = 0.0
    if side == "LONG":
        if key_levels.get("at_support", False):
            level_score = 0.8
            touches = key_levels.get("support_touches", 0)
            if touches >= 3:
                level_score = 1.0
            reasons.append(f"지지선 접촉 ({touches}회)")
    else:
        if key_levels.get("at_resistance", False):
            level_score = 0.8
            touches = key_levels.get("resistance_touches", 0)
            if touches >= 3:
                level_score = 1.0
            reasons.append(f"저항선 접촉 ({touches}회)")

    if key_levels.get("round_number_near", False):
        level_score = min(1.0, level_score + 0.2)
        reasons.append("라운드넘버 근접")

    score += level_score * 0.15

    # --- 5. 캔들 패턴 (15%) ---
    candle_score = 0.0
    strength = candle.get("pattern_strength", 0)

    if side == "LONG":
        if candle.get("bullish_engulfing", False):
            candle_score = 0.8 * strength
            reasons.append("불리시 장악형")
        if candle.get("bullish_pin_bar", False):
            candle_score = max(candle_score, 0.7 * strength)
            reasons.append("불리시 핀바")
    else:
        if candle.get("bearish_engulfing", False):
            candle_score = 0.8 * strength
            reasons.append("베어리시 장악형")
        if candle.get("bearish_pin_bar", False):
            candle_score = max(candle_score, 0.7 * strength)
            reasons.append("베어리시 핀바")

    if candle.get("inside_bar", False):
        candle_score = max(candle_score, 0.3)

    score += min(1.0, candle_score) * 0.15

    # --- 최종 판정 ---
    confidence = round(max(0.0, min(1.0, score)), 3)

    if confidence >= 0.55:
        direction = "BULL" if side == "LONG" else "BEAR"
    elif confidence >= 0.35:
        direction = "NEUTRAL"
    else:
        direction = "BEAR" if side == "LONG" else "BULL"

    # 근거 분해 문자열
    parts = []
    base_pct = round(base_score * 0.20 * 100)
    trend_pct = round(min(1.0, trend_score) * 0.30 * 100)
    vol_pct = round(max(0.0, min(1.0, vol_score)) * 0.20 * 100)
    level_pct = round(level_score * 0.15 * 100)
    candle_pct = round(min(1.0, candle_score) * 0.15 * 100)

    if base_pct > 0:
        parts.append(f"시그널{base_pct}%")
    if trend_pct > 0:
        parts.append(f"추세{trend_pct}%")
    if vol_pct > 0:
        parts.append(f"거래량{vol_pct}%")
    if level_pct > 0:
        parts.append(f"키레벨{level_pct}%")
    if candle_pct > 0:
        parts.append(f"캔들{candle_pct}%")

    breakdown = " + ".join(parts) if parts else "—"

    # 하위 호환: _last_breakdown 캐시
    _last_breakdown[0] = breakdown

    return {
        "direction": direction,
        "confidence": confidence,
        "breakdown": breakdown,
        "reasons": reasons,
    }


# --- 하위 호환 래퍼 ---
_last_breakdown: list[str] = ["—"]


def calc_confidence_v2(
    base: float,
    adx: dict,
    volume: dict,
    structure: dict,
    candle: dict,
    key_levels: dict,
    side: str,
) -> float:
    """하위 호환: 기존 confidence.py와 동일한 시그니처."""
    result = judge_direction(base, adx, volume, structure, candle, key_levels, side)
    return result["confidence"]


def get_last_breakdown() -> str:
    """Return the breakdown string from the last call."""
    return _last_breakdown[0]

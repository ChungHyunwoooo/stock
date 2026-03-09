"""통합 신뢰도 v2 — 다중 컨펌 기반 가중치 신뢰도 공식.

의존성: 없음 (dict 입력만)
"""

from __future__ import annotations


def calc_confidence_v2(
    base: float,
    adx: dict,
    volume: dict,
    structure: dict,
    candle: dict,
    key_levels: dict,
    side: str,
) -> float:
    """통합 신뢰도 v2 계산.

    가중치 배분:
    - 기본 시그널 품질: 20% (전략별 base 값)
    - 추세 정렬: 30% (ADX 강도 × 구조 방향 일치)
    - 거래량 확인: 20% (비율 + OBV + 다이버전스 없음)
    - 키레벨 컨플루언스: 15% (LONG=지지선, SHORT=저항선)
    - 캔들 패턴: 15% (장악형/핀바 출현 × strength)

    Returns:
        0.0 - 1.0
    """
    score = 0.0

    # --- 1. 기본 시그널 품질 (20%) ---
    score += min(1.0, max(0.0, base)) * 0.20

    # --- 2. 추세 정렬 (30%) ---
    trend_score = 0.0

    # ADX 강도 (0-1 정규화)
    adx_val = adx.get("adx", 0)
    if adx_val > 25:
        adx_strength = 1.0
    elif adx_val > 20:
        adx_strength = 0.7
    elif adx_val > 15:
        adx_strength = 0.3
    else:
        adx_strength = 0.0

    # 구조 방향 일치
    trend = structure.get("trend", "RANGING")
    if side == "LONG":
        if trend == "BULLISH":
            direction_match = 1.0
        elif trend == "RANGING":
            direction_match = 0.4
        else:
            direction_match = 0.0
    else:  # SHORT
        if trend == "BEARISH":
            direction_match = 1.0
        elif trend == "RANGING":
            direction_match = 0.4
        else:
            direction_match = 0.0

    # DI 방향 일치 보너스
    di_bonus = 0.0
    trend_dir = adx.get("trend_direction", "NEUTRAL")
    if (side == "LONG" and trend_dir == "BULLISH") or (side == "SHORT" and trend_dir == "BEARISH"):
        di_bonus = 0.2

    trend_score = adx_strength * 0.4 + direction_match * 0.4 + di_bonus
    score += min(1.0, trend_score) * 0.30

    # --- 3. 거래량 확인 (20%) ---
    vol_score = 0.0
    vol_ratio = volume.get("vol_ratio", 0)
    if vol_ratio >= 2.0:
        vol_score += 0.4
    elif vol_ratio >= 1.5:
        vol_score += 0.3
    elif vol_ratio >= 1.2:
        vol_score += 0.2

    # OBV 일치
    obv_trend = volume.get("obv_trend", "FLAT")
    if (side == "LONG" and obv_trend == "RISING") or (side == "SHORT" and obv_trend == "FALLING"):
        vol_score += 0.3

    # 다이버전스 없음 보너스
    if not volume.get("vol_price_divergence", False):
        vol_score += 0.2

    # 클라이맥스 경고 (반대 시그널)
    if volume.get("is_climactic", False):
        vol_score -= 0.3

    score += max(0.0, min(1.0, vol_score)) * 0.20

    # --- 4. 키레벨 컨플루언스 (15%) ---
    level_score = 0.0
    if side == "LONG":
        if key_levels.get("at_support", False):
            level_score = 0.8
            # 터치 횟수 보너스
            touches = key_levels.get("support_touches", 0)
            if touches >= 3:
                level_score = 1.0
    else:  # SHORT
        if key_levels.get("at_resistance", False):
            level_score = 0.8
            touches = key_levels.get("resistance_touches", 0)
            if touches >= 3:
                level_score = 1.0

    # 라운드넘버 보너스
    if key_levels.get("round_number_near", False):
        level_score = min(1.0, level_score + 0.2)

    score += level_score * 0.15

    # --- 5. 캔들 패턴 (15%) ---
    candle_score = 0.0
    strength = candle.get("pattern_strength", 0)

    if side == "LONG":
        if candle.get("bullish_engulfing", False):
            candle_score = 0.8 * strength
        if candle.get("bullish_pin_bar", False):
            candle_score = max(candle_score, 0.7 * strength)
    else:
        if candle.get("bearish_engulfing", False):
            candle_score = 0.8 * strength
        if candle.get("bearish_pin_bar", False):
            candle_score = max(candle_score, 0.7 * strength)

    # Inside bar는 방향 중립이므로 소량 보너스
    if candle.get("inside_bar", False):
        candle_score = max(candle_score, 0.3)

    score += min(1.0, candle_score) * 0.15

    final = round(max(0.0, min(1.0, score)), 3)

    # 근거 분해 문자열 (선택적 접근)
    parts = []
    base_pct = round(min(1.0, max(0.0, base)) * 0.20 * 100)
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

    # Store breakdown as attribute on the float (accessible but non-breaking)
    # Use module-level cache since float can't have attributes
    _last_breakdown[0] = " + ".join(parts) if parts else "—"

    return final


# Module-level cache for last confidence breakdown
_last_breakdown: list[str] = ["—"]


def get_last_breakdown() -> str:
    """Return the breakdown string from the last calc_confidence_v2 call."""
    return _last_breakdown[0]

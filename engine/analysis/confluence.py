"""통합 컨플루언스 점수 시스템.

3가지 독립 엣지:
1. Funding Rate 극단값 → +1점
2. MTF 정렬 → +1점
3. Volume Profile 레벨 → +1점

추가 필터:
- 레짐 필터: ADX>20 or BB Width 확장
- 세션 필터: London/NY 세션 우선

점수 2+ → EXECUTE (72-77% WR 목표)
점수 0-1 → NO TRADE
"""

from __future__ import annotations

from datetime import datetime, timezone

def calc_confluence_score(
    funding_rate: float | None,
    mtf_score: float,
    vpvr: dict,
    side: str,
    adx_val: float = 0.0,
    current_hour_utc: int | None = None,
) -> dict:
    """통합 컨플루언스 점수 계산.

    Args:
        funding_rate: 현재 펀딩비 (None이면 무시)
        mtf_score: MTF 정렬 점수 (0.0~1.0)
        vpvr: VPVR 분석 결과 dict (at_poc, at_vah, at_val 등)
        side: "LONG" or "SHORT"
        adx_val: ADX 값 (레짐 필터용)
        current_hour_utc: 현재 UTC 시간 (세션 필터용, None이면 자동 감지)

    Returns:
        {
            "total_score": int,        # 0-3 총점
            "execute": bool,           # score >= 2 → True
            "funding_point": bool,     # 펀딩비 포인트 획득 여부
            "mtf_point": bool,         # MTF 포인트 획득 여부
            "vp_point": bool,          # VP 포인트 획득 여부
            "regime_ok": bool,         # 레짐 필터 통과 여부
            "session_ok": bool,        # 세션 필터 통과 여부
            "session": str,            # 현재 세션명
            "details": str,            # 사람 읽기용 요약
        }
    """
    side = (side or "").upper()

    # --- 1. Funding Rate 점수 ---
    funding_point = False
    if funding_rate is not None:
        if side == "LONG" and funding_rate < -0.00004:
            funding_point = True
        elif side == "SHORT" and funding_rate > 0.0001:
            funding_point = True

    # --- 2. MTF Confluence 점수 ---
    mtf_score = float(mtf_score) if mtf_score is not None else 0.0
    mtf_point = mtf_score >= 0.55

    # --- 3. Volume Profile 점수 ---
    vpvr = vpvr or {}
    at_poc = bool(vpvr.get("at_poc", False))
    at_vah = bool(vpvr.get("at_vah", False))
    at_val = bool(vpvr.get("at_val", False))
    at_hvn = bool(vpvr.get("at_hvn", False))

    if side == "LONG":
        vp_point = at_val or at_poc or at_hvn
    else:  # SHORT
        vp_point = at_vah or at_poc or at_hvn

    # --- 4. 레짐 필터 ---
    adx_val = float(adx_val) if adx_val is not None else 0.0
    regime_ok = adx_val > 15

    # --- 5. 세션 필터 (정보 제공용, 크립토는 24시간) ---
    if current_hour_utc is None:
        current_hour_utc = datetime.now(timezone.utc).hour

    hour = int(current_hour_utc)

    if 8 <= hour < 12:
        session = "LONDON"
        session_ok = True
    elif 13 <= hour < 17:
        session = "NY_OPEN"
        session_ok = True
    elif 17 <= hour < 21:
        session = "NY_CLOSE"
        session_ok = True
    else:
        session = "OFF_HOURS"
        session_ok = False

    # --- 총점 계산 ---
    total_score = int(funding_point) + int(mtf_point) + int(vp_point)

    # --- execute 결정 ---
    # 레짐 필터 실패 시 항상 False
    # 세션 필터는 크립토 24시간 시장이므로 hard-block하지 않음 (정보 제공만)
    if not regime_ok:
        execute = False
    else:
        execute = total_score >= 2

    # --- details 문자열 ---
    funding_mark = "펀딩✓" if funding_point else "펀딩✗"
    mtf_mark = "MTF✓" if mtf_point else "MTF✗"
    vp_mark = "VP✓" if vp_point else "VP✗"
    regime_mark = "레짐OK" if regime_ok else "레짐NG"

    details = (
        f"{total_score}/3점 [{funding_mark} {mtf_mark} {vp_mark}]"
        f" | {session} | {regime_mark}"
    )

    return {
        "total_score": total_score,
        "execute": execute,
        "funding_point": funding_point,
        "mtf_point": mtf_point,
        "vp_point": vp_point,
        "regime_ok": regime_ok,
        "session_ok": session_ok,
        "session": session,
        "details": details,
    }

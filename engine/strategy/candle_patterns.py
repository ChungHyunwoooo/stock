"""TA-Lib 기반 캔들 패턴 감지 — 보조 시그널.

61종 중 신뢰도 높은 패턴만 선별.
구조적 패턴(쌍바닥/삼각형)의 보조 확인 역할.
"""

from dataclasses import dataclass

import numpy as np
import talib

# 신뢰도 높은 캔들 패턴 (이름, 한글명, 중요도)
# 중요도: 3=강력, 2=보통, 1=참고
CANDLE_PATTERNS: dict[str, tuple[str, int]] = {
    # 반전 패턴 (강력)
    "CDL3WHITESOLDIERS": ("삼백병", 3),
    "CDL3BLACKCROWS": ("삼흑병", 3),
    "CDLMORNINGSTAR": ("샛별형", 3),
    "CDLEVENINGSTAR": ("석별형", 3),
    "CDLMORNINGDOJISTAR": ("도지샛별", 3),
    "CDLEVENINGDOJISTAR": ("도지석별", 3),
    "CDLABANDONEDBABY": ("버림받은아기", 3),
    # 반전 패턴 (보통)
    "CDLENGULFING": ("장악형", 2),
    "CDLPIERCING": ("관통형", 2),
    "CDLDARKCLOUDCOVER": ("먹구름", 2),
    "CDLHAMMER": ("망치형", 2),
    "CDLHANGINGMAN": ("교수형", 2),
    "CDLINVERTEDHAMMER": ("역망치", 2),
    "CDLSHOOTINGSTAR": ("유성형", 2),
    "CDLHARAMI": ("잉태형", 2),
    # 지속 패턴 (참고)
    "CDLRISEFALL3METHODS": ("삼법", 1),
    "CDL3OUTSIDE": ("아웃사이드", 1),
    "CDL3INSIDE": ("인사이드", 1),
    "CDLKICKING": ("키킹", 2),
    "CDLMARUBOZU": ("마루보즈", 1),
    "CDLBELTHOLD": ("벨트홀드", 1),
}

@dataclass
class CandleSignal:
    name: str       # 함수명 (e.g. "CDLENGULFING")
    kr_name: str    # 한글명
    direction: str  # "BULL" | "BEAR"
    strength: int   # TA-Lib 값 (100=일반, 200=확인됨)
    importance: int  # 1~3

def scan_candle_patterns(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    lookback: int = 3,
) -> list[CandleSignal]:
    """최근 N봉에서 감지된 캔들 패턴 반환.

    Args:
        open_, high, low, close: float64 OHLC 배열
        lookback: 최근 N봉 검사 (기본 3)

    Returns:
        감지된 CandleSignal 목록 (중요도 내림차순 정렬)
    """
    results: list[CandleSignal] = []

    for func_name, (kr_name, importance) in CANDLE_PATTERNS.items():
        func = getattr(talib, func_name, None)
        if func is None:
            continue

        try:
            values = func(open_, high, low, close)
        except Exception:
            continue

        # 최근 lookback 봉 검사
        for offset in range(lookback):
            idx = len(values) - 1 - offset
            if idx < 0:
                break
            val = int(values[idx])
            if val == 0:
                continue

            direction = "BULL" if val > 0 else "BEAR"
            results.append(CandleSignal(
                name=func_name,
                kr_name=kr_name,
                direction=direction,
                strength=abs(val),
                importance=importance,
            ))

    # 중요도 → 강도 내림차순
    results.sort(key=lambda s: (s.importance, s.strength), reverse=True)

    # 중복 제거 (같은 패턴 여러 봉에서 감지 시 가장 최근 것만)
    seen = set()
    unique = []
    for s in results:
        if s.name not in seen:
            seen.add(s.name)
            unique.append(s)

    return unique

def format_candle_signals(signals: list[CandleSignal]) -> str:
    """디스코드 메시지용 포맷."""
    if not signals:
        return "캔들: 없음"

    parts = []
    for s in signals[:5]:  # 최대 5개
        star = "*" * s.importance
        icon = "▲" if s.direction == "BULL" else "▼"
        parts.append(f"{icon}{s.kr_name}({star})")
    return " ".join(parts)

def get_candle_bias(signals: list[CandleSignal]) -> tuple[str, float]:
    """캔들 패턴 종합 방향 + 확신도.

    Returns:
        (direction, confidence) — "BULL"|"BEAR"|"NEUTRAL", 0.0~1.0
    """
    if not signals:
        return "NEUTRAL", 0.0

    bull_score = sum(s.importance * s.strength / 100 for s in signals if s.direction == "BULL")
    bear_score = sum(s.importance * s.strength / 100 for s in signals if s.direction == "BEAR")

    total = bull_score + bear_score
    if total == 0:
        return "NEUTRAL", 0.0

    if bull_score > bear_score:
        return "BULL", min(bull_score / (total + 3), 1.0)
    elif bear_score > bull_score:
        return "BEAR", min(bear_score / (total + 3), 1.0)
    return "NEUTRAL", 0.0

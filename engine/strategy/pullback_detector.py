"""눌림목(Pullback) 패턴 감지기.

EMA 눌림목: 추세 중 EMA까지 되돌림 후 반전 캔들 확인 시 진입.

조건:
  LONG:
    1. 정배열 (EMA21 > EMA55)
    2. 가격이 EMA21 아래로 터치 (눌림)
    3. 다시 EMA21 위로 복귀 (반등)
    4. 반전 캔들 확인 (선택)
  SHORT: 역배열에서 반대

SL/TP: 지지·저항 기반.
"""

from __future__ import annotations

import numpy as np
import talib

from engine.strategy.pattern_detector import (
    PatternSignal,
    find_local_extrema,
    confirmed_before,
    _find_next_resistance,
    _find_next_support,
    _SL_MARGIN,
    _TP_FALLBACK_RATIO,
)

# 반전 캔들 감지 함수 (TA-Lib)
_BULL_CANDLE_FUNCS = [
    "CDLHAMMER", "CDLENGULFING", "CDLMORNINGSTAR",
    "CDLMORNINGDOJISTAR", "CDL3WHITESOLDIERS", "CDLPIERCING",
]
_BEAR_CANDLE_FUNCS = [
    "CDLSHOOTINGSTAR", "CDLENGULFING", "CDLEVENINGSTAR",
    "CDLEVENINGDOJISTAR", "CDL3BLACKCROWS", "CDLDARKCLOUDCOVER",
]

def _has_reversal_candle(
    opn: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
    i: int, side: str, lookback: int = 3,
) -> bool:
    """최근 N봉 내 반전 캔들 존재 여부."""
    funcs = _BULL_CANDLE_FUNCS if side == "LONG" else _BEAR_CANDLE_FUNCS
    for fname in funcs:
        func = getattr(talib, fname, None)
        if func is None:
            continue
        try:
            result = func(opn, high, low, close)
            for offset in range(lookback):
                idx = i - offset
                if idx < 0:
                    break
                val = int(result[idx])
                if side == "LONG" and val > 0:
                    return True
                if side == "SHORT" and val < 0:
                    return True
        except Exception:
            continue
    return False

def detect_pullback(
    opn: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    i: int,
    ema21: np.ndarray,
    ema55: np.ndarray,
    low_mins: list[int],
    high_maxs: list[int],
    require_candle: bool = True,
) -> PatternSignal | None:
    """현재 봉(i)에서 눌림목 패턴 감지.

    Args:
        require_candle: True면 반전 캔들 확인 필수.
    """
    if i < 10:
        return None

    price = float(close[i])
    e21 = float(ema21[i])
    e55 = float(ema55[i])

    # ── LONG 눌림목: 정배열 + EMA21 터치 후 복귀
    if e21 > e55:
        # 최근 5봉 내 EMA21 아래 터치 확인
        touched = False
        for j in range(1, 6):
            if i - j < 0:
                break
            if float(low[i - j]) <= float(ema21[i - j]):
                touched = True
                break

        if not touched:
            return None

        # 현재 봉이 EMA21 위로 복귀
        if price <= e21:
            return None

        # 반전 캔들 확인
        if require_candle and not _has_reversal_candle(opn, high, low, close, i, "LONG"):
            return None

        entry = price
        # SL: 직전 지지 또는 EMA55
        support = _find_next_support(entry, entry - e55, low, low_mins, i)
        sl = support * (1 - _SL_MARGIN) if support else e55 * (1 - _SL_MARGIN)

        # SL이 진입가보다 높으면 무효
        if sl >= entry:
            return None

        sl_dist = entry - sl
        # TP: 다음 저항
        resistance = _find_next_resistance(entry, sl_dist, high, high_maxs, i)
        tp = resistance if resistance else entry + _TP_FALLBACK_RATIO * sl_dist

        return PatternSignal(
            pattern="PULLBACK", side="LONG",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            bar_index=i,
            metadata={"ema21": e21, "ema55": e55, "type": "EMA_PULLBACK"},
        )

    # ── SHORT 눌림목: 역배열 + EMA21 위 터치 후 하락 복귀
    elif e55 > e21:
        touched = False
        for j in range(1, 6):
            if i - j < 0:
                break
            if float(high[i - j]) >= float(ema21[i - j]):
                touched = True
                break

        if not touched:
            return None

        if price >= e21:
            return None

        if require_candle and not _has_reversal_candle(opn, high, low, close, i, "SHORT"):
            return None

        entry = price
        resistance = _find_next_resistance(entry, e55 - entry, high, high_maxs, i)
        sl = resistance * (1 + _SL_MARGIN) if resistance else e55 * (1 + _SL_MARGIN)

        if sl <= entry:
            return None

        sl_dist = sl - entry
        support = _find_next_support(entry, sl_dist, low, low_mins, i)
        tp = support if support else entry - _TP_FALLBACK_RATIO * sl_dist

        return PatternSignal(
            pattern="PULLBACK", side="SHORT",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            bar_index=i,
            metadata={"ema21": e21, "ema55": e55, "type": "EMA_PULLBACK"},
        )

    return None

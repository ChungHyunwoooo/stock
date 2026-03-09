"""스마트머니 컨셉 (SMC) 분석 — BOS/CHoCH/Order Block/FVG.

5-bar 피봇 기반 시장 구조 변화 감지.
의존성: numpy, pandas (talib 불필요)
성능: ~2ms
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_smc(df: pd.DataFrame, lookback: int = 50) -> dict:
    """SMC 분석.

    5-bar 피봇으로 스윙을 감지하고,
    BOS(구조 돌파), CHoCH(성격 변환), Order Block, FVG를 판별.

    Returns:
        {
            bos_up: bool,              # Break of Structure 상방
            bos_down: bool,            # Break of Structure 하방
            choch_up: bool,            # Change of Character 상방 (하락→상승 전환)
            choch_down: bool,          # Change of Character 하방 (상승→하락 전환)
            order_block_bull: float,   # 불리시 OB 가격 (0=없음)
            order_block_bear: float,   # 베어리시 OB 가격 (0=없음)
            fvg_bull: bool,            # Fair Value Gap 불리시
            fvg_bear: bool,            # Fair Value Gap 베어리시
            fvg_bull_low: float,       # FVG 불리시 하단
            fvg_bull_high: float,      # FVG 불리시 상단
        }
    """
    result = {
        "bos_up": False,
        "bos_down": False,
        "choch_up": False,
        "choch_down": False,
        "order_block_bull": 0.0,
        "order_block_bear": 0.0,
        "fvg_bull": False,
        "fvg_bear": False,
        "fvg_bull_low": 0.0,
        "fvg_bull_high": 0.0,
    }

    if len(df) < lookback:
        return result

    high = df["high"].values[-lookback:]
    low = df["low"].values[-lookback:]
    close = df["close"].values[-lookback:]
    open_ = df["open"].values[-lookback:]

    # -----------------------------------------------------------------
    # 1. 5-bar pivot swing detection
    # -----------------------------------------------------------------
    swing_highs = []  # (index, price)
    swing_lows = []   # (index, price)

    for i in range(2, len(high) - 2):
        if (high[i] > high[i - 1] and high[i] > high[i - 2]
                and high[i] > high[i + 1] and high[i] > high[i + 2]):
            swing_highs.append((i, float(high[i])))

        if (low[i] < low[i - 1] and low[i] < low[i - 2]
                and low[i] < low[i + 1] and low[i] < low[i + 2]):
            swing_lows.append((i, float(low[i])))

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return result

    curr_close = float(close[-1])

    # -----------------------------------------------------------------
    # 2. BOS detection — 종가가 직전 스윙 돌파
    # -----------------------------------------------------------------
    last_sh = swing_highs[-1][1]
    last_sl = swing_lows[-1][1]
    prev_sh = swing_highs[-2][1]
    prev_sl = swing_lows[-2][1]

    result["bos_up"] = curr_close > last_sh
    result["bos_down"] = curr_close < last_sl

    # -----------------------------------------------------------------
    # 3. CHoCH detection — 추세 방향 전환
    #    HH/HL 시퀀스에서 LH/LL로 전환 = choch_down
    #    LH/LL 시퀀스에서 HH/HL로 전환 = choch_up
    # -----------------------------------------------------------------
    # 이전 추세 판별: 마지막 2개 스윙 비교
    prev_trend_up = (last_sh > prev_sh) and (last_sl > prev_sl)   # HH + HL
    prev_trend_down = (last_sh < prev_sh) and (last_sl < prev_sl)  # LH + LL

    # 현재 가격이 구조를 깨는지 확인
    if prev_trend_down and curr_close > last_sh:
        # 하락 추세에서 최근 고점 돌파 = 상방 전환
        result["choch_up"] = True
    if prev_trend_up and curr_close < last_sl:
        # 상승 추세에서 최근 저점 이탈 = 하방 전환
        result["choch_down"] = True

    # -----------------------------------------------------------------
    # 4. Order Block — BOS 직전 마지막 반대 캔들
    # -----------------------------------------------------------------
    if result["bos_up"] or result["choch_up"]:
        # 불리시 OB: BOS↑ 전 마지막 음봉 (close < open)
        sh_idx = swing_highs[-1][0]
        for j in range(sh_idx, max(sh_idx - 10, 0), -1):
            if close[j] < open_[j]:  # 음봉
                result["order_block_bull"] = float(low[j])
                break

    if result["bos_down"] or result["choch_down"]:
        # 베어리시 OB: BOS↓ 전 마지막 양봉 (close > open)
        sl_idx = swing_lows[-1][0]
        for j in range(sl_idx, max(sl_idx - 10, 0), -1):
            if close[j] > open_[j]:  # 양봉
                result["order_block_bear"] = float(high[j])
                break

    # -----------------------------------------------------------------
    # 5. FVG (Fair Value Gap) — 최근 3봉 갭
    # -----------------------------------------------------------------
    # 최근 10봉 내에서 가장 최신 FVG 탐색
    n = len(high)
    for i in range(n - 2, max(n - 12, 1), -1):
        # Bullish FVG: low[i+1] > high[i-1] (갭업)
        if low[i + 1] > high[i - 1] if i + 1 < n and i - 1 >= 0 else False:
            result["fvg_bull"] = True
            result["fvg_bull_low"] = float(high[i - 1])
            result["fvg_bull_high"] = float(low[i + 1])
            break

    for i in range(n - 2, max(n - 12, 1), -1):
        # Bearish FVG: high[i+1] < low[i-1] (갭다운)
        if i + 1 < n and i - 1 >= 0 and high[i + 1] < low[i - 1]:
            result["fvg_bear"] = True
            break

    return result

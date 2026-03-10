"""방향 예측기 — 레짐 필터 대체용.

후행 레짐 판단(EMA200) 대신, 선행 신호로 LONG/SHORT 편향을 결정.
각 예측기는 현재 봉 기준 과거 데이터만 사용 (look-ahead 없음).

예측기 목록:
  1. Momentum Score — N일 수익률 방향
  2. EMA Cross — EMA 단기/중기 교차 방향
  3. Structure — 최근 고점/저점의 상승/하락 패턴
  4. Multi-Signal — 1~3 복합 투표
"""

import numpy as np

def predict_momentum(close: np.ndarray, i: int, lookback: int = 20) -> str:
    """N봉 전 대비 수익률 방향.

    Returns: "LONG" | "SHORT" | "NEUTRAL"
    """
    if i < lookback:
        return "NEUTRAL"
    ret = (close[i] - close[i - lookback]) / close[i - lookback]
    if ret > 0.01:
        return "LONG"
    elif ret < -0.01:
        return "SHORT"
    return "NEUTRAL"

def predict_ema_cross(close: np.ndarray, i: int,
                      ema_fast: np.ndarray, ema_slow: np.ndarray) -> str:
    """EMA 단기/중기 교차 방향.

    fast > slow → LONG, fast < slow → SHORT
    """
    if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]):
        return "NEUTRAL"
    if ema_fast[i] > ema_slow[i]:
        return "LONG"
    elif ema_fast[i] < ema_slow[i]:
        return "SHORT"
    return "NEUTRAL"

def predict_structure(high: np.ndarray, low: np.ndarray, i: int,
                      lookback: int = 20, order: int = 5) -> str:
    """최근 고점/저점의 방향성.

    Higher highs + higher lows → LONG
    Lower highs + lower lows → SHORT
    """
    if i < lookback + order:
        return "NEUTRAL"

    # 최근 lookback 내 확정된 극값 찾기
    mins = []
    maxs = []
    for k in range(order, i - order + 1):
        if k < i - lookback:
            continue
        if all(low[k] <= low[k - j] for j in range(1, order + 1)) and \
           all(low[k] <= low[k + j] for j in range(1, order + 1)):
            mins.append(k)
        if all(high[k] >= high[k - j] for j in range(1, order + 1)) and \
           all(high[k] >= high[k + j] for j in range(1, order + 1)):
            maxs.append(k)

    if len(mins) < 2 or len(maxs) < 2:
        return "NEUTRAL"

    # 최근 2개 비교
    higher_lows = low[mins[-1]] > low[mins[-2]]
    higher_highs = high[maxs[-1]] > high[maxs[-2]]
    lower_lows = low[mins[-1]] < low[mins[-2]]
    lower_highs = high[maxs[-1]] < high[maxs[-2]]

    if higher_highs and higher_lows:
        return "LONG"
    elif lower_highs and lower_lows:
        return "SHORT"
    return "NEUTRAL"

def predict_multi(close: np.ndarray, high: np.ndarray, low: np.ndarray,
                  i: int, ema_fast: np.ndarray, ema_slow: np.ndarray) -> str:
    """3개 예측기 다수결 투표.

    2개 이상 동의 → 해당 방향. 아니면 NEUTRAL.
    """
    votes = [
        predict_momentum(close, i),
        predict_ema_cross(close, i, ema_fast, ema_slow),
        predict_structure(high, low, i),
    ]

    long_count = votes.count("LONG")
    short_count = votes.count("SHORT")

    if long_count >= 2:
        return "LONG"
    elif short_count >= 2:
        return "SHORT"
    return "NEUTRAL"

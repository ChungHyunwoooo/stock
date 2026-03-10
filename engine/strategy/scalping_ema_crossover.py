"""EMA 9/21 Crossover + RSI 14 스캘핑 전략.

YouTube/트레이딩 커뮤니티에서 가장 인기 있는 1분봉 스캘핑 전략.
- EMA 9/21 교차로 추세 방향 감지
- RSI 14로 과매수/과매도 필터링
- 1:2 R:R (SL 0.3%, TP 0.6%)

References:
- DaviddTech "Easy 1 Minute Scalping Strategy"
- FXOpen "Four Popular 1-Minute Scalping Strategies"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ScalpSignal(str, Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass(slots=True)
class ScalpResult:
    """스캘핑 감지 결과."""
    signal: ScalpSignal
    entry_price: float
    stop_loss: float
    take_profit: float
    ema_fast: float
    ema_slow: float
    rsi: float
    reason: str


# ── 기본 설정 ───────────────────────────────────────────────

DEFAULT_CONFIG = {
    "ema_fast": 9,
    "ema_slow": 21,
    "rsi_period": 14,
    "rsi_long_min": 50,
    "rsi_long_max": 70,
    "rsi_short_min": 30,
    "rsi_short_max": 50,
    "sl_pct": 0.3,
    "tp_pct": 0.6,
}


# ── 지표 계산 ───────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI 계산."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 → RSI = 100 (전부 상승), avg_gain == 0 → RSI = 0 (전부 하락)
    rsi = rsi.fillna(50)
    return rsi


# ── 감지기 ──────────────────────────────────────────────────

def detect_scalp_signal(
    df: pd.DataFrame,
    config: dict | None = None,
) -> ScalpResult:
    """EMA Crossover + RSI 스캘핑 신호 감지.

    Args:
        df: OHLCV DataFrame (최소 30봉 이상)
        config: 설정 override

    Returns:
        ScalpResult
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    if len(df) < cfg["ema_slow"] + 5:
        return ScalpResult(
            signal=ScalpSignal.NONE,
            entry_price=0, stop_loss=0, take_profit=0,
            ema_fast=0, ema_slow=0, rsi=0,
            reason="데이터 부족",
        )

    close = df["close"]
    ema_fast = calc_ema(close, cfg["ema_fast"])
    ema_slow = calc_ema(close, cfg["ema_slow"])
    rsi = calc_rsi(close, cfg["rsi_period"])

    # 현재 + 이전 값
    ema_f_now = float(ema_fast.iloc[-1])
    ema_s_now = float(ema_slow.iloc[-1])
    ema_f_prev = float(ema_fast.iloc[-2])
    ema_s_prev = float(ema_slow.iloc[-2])
    rsi_now = float(rsi.iloc[-1])
    price_now = float(close.iloc[-1])

    # 크로스 감지
    golden_cross = ema_f_prev <= ema_s_prev and ema_f_now > ema_s_now
    death_cross = ema_f_prev >= ema_s_prev and ema_f_now < ema_s_now

    signal = ScalpSignal.NONE
    sl = 0.0
    tp = 0.0
    reason = ""

    if golden_cross and cfg["rsi_long_min"] < rsi_now < cfg["rsi_long_max"]:
        signal = ScalpSignal.LONG
        sl = price_now * (1 - cfg["sl_pct"] / 100)
        tp = price_now * (1 + cfg["tp_pct"] / 100)
        reason = f"골든크로스 EMA{cfg['ema_fast']}/{cfg['ema_slow']} + RSI={rsi_now:.1f}"

    elif death_cross and cfg["rsi_short_min"] < rsi_now < cfg["rsi_short_max"]:
        signal = ScalpSignal.SHORT
        sl = price_now * (1 + cfg["sl_pct"] / 100)
        tp = price_now * (1 - cfg["tp_pct"] / 100)
        reason = f"데드크로스 EMA{cfg['ema_fast']}/{cfg['ema_slow']} + RSI={rsi_now:.1f}"

    return ScalpResult(
        signal=signal,
        entry_price=price_now,
        stop_loss=round(sl, 2),
        take_profit=round(tp, 2),
        ema_fast=round(ema_f_now, 2),
        ema_slow=round(ema_s_now, 2),
        rsi=round(rsi_now, 2),
        reason=reason,
    )

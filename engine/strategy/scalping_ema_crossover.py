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

from engine.strategy.scalping_risk import (
    ScalpRiskConfig,
    ScalpRiskResult,
    calculate_scalp_risk,
)

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
    # 동적 리스크 (calculate_scalp_risk 사용 시 채워짐)
    risk: ScalpRiskResult | None = None


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
    capital: float | None = None,
    risk_config: ScalpRiskConfig | None = None,
) -> ScalpResult:
    """EMA Crossover + RSI 스캘핑 신호 감지.

    Args:
        df: OHLCV DataFrame (최소 30봉 이상)
        config: 전략 설정 override
        capital: 가용 자본 (USDT). 지정 시 동적 리스크 계산 활성화.
        risk_config: 리스크 설정. capital 지정 시만 사용.

    Returns:
        ScalpResult (capital 지정 시 risk 필드 채워짐)
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

    # 동적 리스크 계산 (capital 지정 + 신호 있을 때)
    risk_result: ScalpRiskResult | None = None
    if signal != ScalpSignal.NONE and capital is not None:
        risk_result = calculate_scalp_risk(
            df=df,
            entry_price=price_now,
            side=signal.value,
            capital=capital,
            config=risk_config,
        )
        # 동적 SL/TP로 덮어쓰기
        sl = risk_result.stop_loss
        tp = risk_result.take_profit
        reason = f"{reason} | {risk_result.reason}"

    from engine.strategy.scalping_risk import _price_precision
    prec = _price_precision(price_now)

    return ScalpResult(
        signal=signal,
        entry_price=price_now,
        stop_loss=round(sl, prec),
        take_profit=round(tp, prec),
        ema_fast=round(ema_f_now, 2),
        ema_slow=round(ema_s_now, 2),
        rsi=round(rsi_now, 2),
        reason=reason,
        risk=risk_result,
    )

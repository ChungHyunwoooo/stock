"""S4: Funding Rate Contrarian — 과열 반대편에 서기.

When funding rate is extremely positive (longs paying shorts),
the market is over-leveraged long → look for short opportunities.
Vice versa for extremely negative funding.
"""

from __future__ import annotations

import logging

import pandas as pd
import talib

from engine.data.provider_crypto import (
    fetch_funding_rate,
    fetch_funding_rates_batch,
)
from engine.notifications.alert_discord import Signal

logger = logging.getLogger(__name__)


def fetch_funding_rates(symbols: list[str]) -> dict[str, float]:
    """Fetch funding rates for multiple symbols.

    하위 호환용 래퍼. 신규 코드는 fetch_funding_rates_batch 사용.
    """
    return fetch_funding_rates_batch(symbols)

def scan_funding_rate(
    df: pd.DataFrame,
    symbol: str,
    funding_rate: float,
    regime: str = "SELECTIVE",
    high_threshold: float = 0.0005,
    low_threshold: float = -0.0005,
    sl_pct: float = 0.008,
    tp1_pct: float = 0.008,
    tp2_pct: float = 0.015,
    leverage: int = 2,
) -> Signal | None:
    """Generate signal based on extreme funding rate + price action.

    Conditions (SHORT — high funding):
    - Funding rate > high_threshold (longs overleveraged)
    - Regime is NOT ALT_SEASON (don't short in strong uptrend)
    - RSI > 60 (price hasn't already corrected)
    - Bearish candle confirmation

    Conditions (LONG — low funding):
    - Funding rate < low_threshold (shorts overleveraged)
    - Regime is NOT BEAR_MARKET
    - RSI < 40 (price hasn't already bounced)
    - Bullish candle confirmation
    """
    if len(df) < 20:
        return None

    close = float(df["close"].iloc[-1])
    rsi = float(talib.RSI(df["close"].values, timeperiod=14)[-1])
    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    fr_pct = funding_rate * 100  # for display

    # HIGH funding → SHORT
    if funding_rate > high_threshold and regime != "ALT_SEASON" and rsi > 55 and is_bearish:
        return Signal(
            strategy="S4_FUNDING_RATE",
            symbol=symbol,
            side="SHORT",
            entry=close,
            stop_loss=round(close * (1 + sl_pct), 6),
            take_profits=[round(close * (1 - tp1_pct), 6), round(close * (1 - tp2_pct), 6)],
            leverage=leverage,
            timeframe="8h",
            confidence=min(1.0, abs(funding_rate) / 0.003),
            reason=f"펀딩비 +{fr_pct:.3f}% (롱 과열) + RSI {rsi:.0f} + 음봉 확인",
        )

    # LOW funding → LONG
    if funding_rate < low_threshold and regime != "BEAR_MARKET" and rsi < 45 and is_bullish:
        return Signal(
            strategy="S4_FUNDING_RATE",
            symbol=symbol,
            side="LONG",
            entry=close,
            stop_loss=round(close * (1 - sl_pct), 6),
            take_profits=[round(close * (1 + tp1_pct), 6), round(close * (1 + tp2_pct), 6)],
            leverage=leverage,
            timeframe="8h",
            confidence=min(1.0, abs(funding_rate) / 0.003),
            reason=f"펀딩비 {fr_pct:.3f}% (숏 과열) + RSI {rsi:.0f} + 양봉 확인",
        )

    return None

def is_funding_extreme(rate: float, side: str) -> bool:
    """펀딩비가 해당 방향의 극단값인지 확인.

    실제 바이낸스 데이터 기반 (2024-06-01~2025-03-01):
    LONG 진입 조건: rate < -0.00004 (P10, 숏 과열)
    SHORT 진입 조건: rate > 0.0001 (P90, 롱 과열)
    """
    if side == "LONG":
        return rate < -0.00004
    elif side == "SHORT":
        return rate > 0.0001
    return False

def funding_signal_strength(rate: float) -> float:
    """펀딩비 극단도를 0.0~1.0으로 정규화.

    |rate| / 0.0005 (실제 데이터 P99 ≈ 0.05% 기반)
    """
    return min(1.0, abs(rate) / 0.0005)

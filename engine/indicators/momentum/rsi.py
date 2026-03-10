"""RSI(상대강도지수) 인디케이터 — 과매수/과매도 및 다이버전스 감지."""

from __future__ import annotations

import numpy as np
import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def rsi(close: Array, period: int = 14) -> SingleResult:
    """RSI 계산."""
    c = _to_numpy(close)
    values = talib.RSI(c, timeperiod=period)
    return SingleResult.from_array(values)


def is_oversold(close: Array, period: int = 14, threshold: float = 30) -> bool:
    """현재 RSI가 임계값 이하이면 True (과매도)."""
    result = rsi(close, period)
    return not np.isnan(result.current) and result.current <= threshold


def is_overbought(close: Array, period: int = 14, threshold: float = 70) -> bool:
    """현재 RSI가 임계값 이상이면 True (과매수)."""
    result = rsi(close, period)
    return not np.isnan(result.current) and result.current >= threshold


def divergence(close: Array, period: int = 14, lookback: int = 20) -> str:
    """RSI 다이버전스 감지. 반환값: 'bullish', 'bearish', 'none'."""
    c = _to_numpy(close)
    if len(c) < lookback + period:
        return "none"
    values = talib.RSI(c, timeperiod=period)
    price_window = c[-lookback:]
    rsi_window = values[-lookback:]
    valid = ~np.isnan(rsi_window)
    if valid.sum() < 4:
        return "none"
    price_w = price_window[valid]
    rsi_w = rsi_window[valid]
    price_low_idx = int(np.argmin(price_w))
    rsi_low_idx = int(np.argmin(rsi_w))
    price_high_idx = int(np.argmax(price_w))
    rsi_high_idx = int(np.argmax(rsi_w))
    if price_low_idx > len(price_w) // 2 and rsi_low_idx < len(rsi_w) // 2:
        return "bullish"
    if price_high_idx > len(price_w) // 2 and rsi_high_idx < len(rsi_w) // 2:
        return "bearish"
    return "none"


def describe() -> dict:
    """RSI 인디케이터 메타데이터."""
    return {
        "name": "RSI",
        "full_name": "Relative Strength Index",
        "range": [0, 100],
        "oversold": 30,
        "overbought": 70,
        "default_period": 14,
        "description": "30 이하 과매도, 70 이상 과매수",
    }

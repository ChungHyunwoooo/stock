"""슬리피지 시뮬레이션 모듈.

슬리피지 모델:
  1. 고정 비율 (fixed_pct) — 진입/청산 시 고정 % 불리하게 체결
  2. 변동성 비례 (volatility) — ATR 기반 슬리피지
  3. 혼합 (hybrid) — 고정 + 변동성 비례

적용 방식:
  - LONG 진입: entry_price * (1 + slippage)
  - LONG 청산: exit_price * (1 - slippage)
  - SHORT 진입: entry_price * (1 - slippage)
  - SHORT 청산: exit_price * (1 + slippage)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SlippageConfig:
    model: str = "fixed"    # "fixed" | "volatility" | "hybrid"
    fixed_pct: float = 0.01  # 고정 슬리피지 (%, 편도)
    vol_multiplier: float = 0.1  # ATR 대비 슬리피지 비율
    atr_period: int = 14


def calc_slippage(
    config: SlippageConfig,
    price: float,
    atr: float = 0.0,
) -> float:
    """슬리피지 금액 계산 (항상 양수)."""
    if config.model == "fixed":
        return price * config.fixed_pct / 100

    if config.model == "volatility":
        return atr * config.vol_multiplier

    # hybrid
    fixed = price * config.fixed_pct / 100
    vol = atr * config.vol_multiplier
    return max(fixed, vol)


def apply_entry_slippage(
    price: float, side: str, slippage: float,
) -> float:
    """진입가에 슬리피지 적용 (불리하게)."""
    if side == "LONG":
        return price + slippage
    return price - slippage


def apply_exit_slippage(
    price: float, side: str, slippage: float,
) -> float:
    """청산가에 슬리피지 적용 (불리하게)."""
    if side == "LONG":
        return price - slippage
    return price + slippage


def calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
             period: int = 14) -> np.ndarray:
    """True Range 기반 ATR 계산."""
    n = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for j in range(1, n):
        tr[j] = max(
            high[j] - low[j],
            abs(high[j] - close[j - 1]),
            abs(low[j] - close[j - 1]),
        )
    atr = np.zeros(n)
    atr[:period] = np.nan
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        for j in range(period, n):
            atr[j] = (atr[j - 1] * (period - 1) + tr[j]) / period
    return atr

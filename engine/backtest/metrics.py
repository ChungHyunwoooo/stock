
from __future__ import annotations

import math

import pandas as pd

def compute_total_return(equity_curve: pd.Series) -> float:
    """Total return as a fraction (e.g. 0.25 = 25%)."""
    if len(equity_curve) < 2 or equity_curve.iloc[0] == 0:
        return 0.0
    return (equity_curve.iloc[-1] - equity_curve.iloc[0]) / equity_curve.iloc[0]

def compute_sharpe_ratio(equity_curve: pd.Series, periods_per_year: int = 252) -> float | None:
    """Annualized Sharpe ratio (risk-free rate = 0)."""
    returns = equity_curve.pct_change().dropna()
    if len(returns) < 2:
        return None
    std = returns.std()
    if std == 0:
        return None
    return float((returns.mean() / std) * math.sqrt(periods_per_year))

def compute_max_drawdown(equity_curve: pd.Series) -> float | None:
    """Maximum peak-to-trough drawdown as a fraction (e.g. -0.15 = -15%)."""
    if len(equity_curve) < 2:
        return None
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(drawdown.min())

def compute_win_rate(pnls: list[float]) -> float:
    """승률 계산 (0.0 ~ 1.0)."""
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)

def compute_profit_factor(pnls: list[float]) -> float:
    """Profit Factor = 총이익 / 총손실. 손실 없으면 inf 반환."""
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss

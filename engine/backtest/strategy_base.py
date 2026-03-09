"""전략 백테스트 공통 모듈 — 데이터 타입, 데이터 로딩, 메트릭 계산."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine.data.base import get_provider


@dataclass
class StrategyTrade:
    strategy: str
    entry_date: str
    exit_date: str
    side: str  # "LONG" | "SHORT"
    entry_price: float
    exit_price: float
    exit_reason: str  # "TP" | "SL" | "TIME" | "END"
    pnl_pct: float  # 레버리지·수수료 반영 후 %
    market_regime: str  # "BULL" | "BEAR" | "RANGE"


@dataclass
class StrategyResult:
    strategy: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    trades: list[StrategyTrade] = field(default_factory=list)


def load_ohlcv(symbol: str, start: str, end: str, timeframe: str,
               lookback_bars: int = 300, exchange: str = "binance") -> pd.DataFrame:
    """OHLCV 데이터 로드. lookback 포함."""
    provider = get_provider("crypto_spot", exchange=exchange)
    delta = _tf_to_timedelta(timeframe)
    tf_start = (pd.Timestamp(start) - delta * lookback_bars).strftime("%Y-%m-%d")
    df = provider.fetch_ohlcv(symbol, tf_start, end, timeframe)
    if df.empty:
        raise ValueError(f"{symbol} {timeframe} 데이터 없음")
    return df


def detect_regime(df_1d: pd.DataFrame) -> str:
    """D1 EMA200 기반 시장 레짐 판단."""
    if len(df_1d) < 200:
        return "RANGE"
    close = df_1d["close"].values
    ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().values
    last_close = float(close[-1])
    last_ema = float(ema200[-1])
    pct = (last_close - last_ema) / last_ema
    if pct > 0.02:
        return "BULL"
    elif pct < -0.02:
        return "BEAR"
    return "RANGE"


def calc_metrics(trades: list[StrategyTrade]) -> StrategyResult | None:
    """트레이드 리스트 → 메트릭 집계."""
    if not trades:
        return None
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return StrategyResult(
        strategy=trades[0].strategy,
        symbol="MULTI",
        timeframe="1h",
        start_date=trades[0].entry_date[:10],
        end_date=trades[-1].exit_date[:10],
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(win_rate, 1),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(pf, 2),
        trades=trades,
    )


def get_start_idx(df: pd.DataFrame, start: str) -> int:
    """백테스트 시작 인덱스 (워밍업 후)."""
    start_ts = pd.Timestamp(start, tz="UTC")
    mask = df.index >= start_ts
    if not mask.any():
        raise ValueError(f"{start} 이후 데이터 없음")
    idx = int(mask.argmax())
    return max(idx, 200)  # 최소 200봉 워밍업


def _tf_to_timedelta(tf: str) -> pd.Timedelta:
    mapping = {
        "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15),
        "1h": pd.Timedelta(hours=1),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
    }
    return mapping.get(tf, pd.Timedelta(hours=1))

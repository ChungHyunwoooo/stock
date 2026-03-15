"""Open Interest 필터 — Binance Futures OI 기반 시장 과열 감지.

OI 급증 = 새로운 포지션 진입 증가 → 과열 가능성
OI 급감 = 포지션 청산 → 추세 약화

사용법:
    from engine.strategy.oi_filter import fetch_oi, is_oi_extreme

    oi_data = fetch_oi("BTC/USDT:USDT")
    if is_oi_extreme(oi_data, "entry_blocked"):
        skip_entry()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from engine.data.provider_crypto import (
    fetch_oi as _fetch_oi_raw,
    fetch_oi_history as _fetch_oi_history_raw,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OIData:
    """Open Interest 데이터."""
    symbol: str
    oi_value: float        # OI (계약 수)
    oi_notional: float     # OI × 가격 (USDT)
    price: float
    timestamp: int


@dataclass(slots=True)
class OIAnalysis:
    """OI 분석 결과."""
    symbol: str
    current_oi: float
    oi_change_pct: float   # 이전 대비 OI 변화율 (%)
    oi_rank: float         # 최근 분포에서 순위 (0~1)
    is_extreme_high: bool  # OI 급증 (과열)
    is_extreme_low: bool   # OI 급감 (추세 약화)


def fetch_oi(symbol: str) -> OIData | None:
    """현재 OI 조회."""
    raw = _fetch_oi_raw(symbol)
    if raw is None:
        return None
    return OIData(
        symbol=raw["symbol"],
        oi_value=raw["oi_value"],
        oi_notional=raw["oi_notional"],
        price=raw["price"],
        timestamp=raw["timestamp"],
    )


def fetch_oi_history(
    symbol: str,
    timeframe: str = "5m",
    limit: int = 100,
) -> list[OIData]:
    """OI 히스토리 조회."""
    raw_list = _fetch_oi_history_raw(symbol, timeframe, limit)
    return [
        OIData(
            symbol=symbol,
            oi_value=h["oi_value"],
            oi_notional=h["oi_notional"],
            price=0,
            timestamp=h["timestamp"],
        )
        for h in raw_list
    ]


def analyze_oi(
    symbol: str,
    high_pctile: float = 0.9,
    low_pctile: float = 0.1,
    history_limit: int = 100,
) -> OIAnalysis | None:
    """OI 분석: 현재 OI가 최근 분포에서 어디에 위치하는지."""
    history = fetch_oi_history(symbol, limit=history_limit)
    if len(history) < 20:
        return None

    oi_values = [h.oi_value for h in history if h.oi_value > 0]
    if len(oi_values) < 20:
        return None

    current_oi = oi_values[-1]
    prev_oi = oi_values[-2] if len(oi_values) > 1 else current_oi
    oi_change_pct = (current_oi - prev_oi) / prev_oi * 100 if prev_oi > 0 else 0

    # percentile rank
    rank = sum(1 for v in oi_values if v < current_oi) / max(len(oi_values) - 1, 1)

    return OIAnalysis(
        symbol=symbol,
        current_oi=current_oi,
        oi_change_pct=round(oi_change_pct, 2),
        oi_rank=round(rank, 4),
        is_extreme_high=rank >= high_pctile,
        is_extreme_low=rank <= low_pctile,
    )


def should_skip_entry(symbol: str) -> bool:
    """OI 기반 진입 스킵 판단.

    OI가 상위 90% 이상이면 과열 → 진입 비추.
    """
    analysis = analyze_oi(symbol)
    if analysis is None:
        return False  # 조회 실패 시 통과
    if analysis.is_extreme_high:
        logger.info("OI 과열: %s (rank=%.2f, change=%+.1f%%)",
                     symbol, analysis.oi_rank, analysis.oi_change_pct)
        return True
    return False

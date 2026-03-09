"""engine.analysis — 트레이딩 분석 모듈 라이브러리.

심볼당 1회 `build_context(df)`를 호출하면 모든 분석 결과를 dict로 반환.
각 모듈은 독립적으로 import/테스트/교체 가능.
"""

from __future__ import annotations

import pandas as pd

from engine.analysis.market_structure import detect_market_structure
from engine.analysis.candle_patterns import detect_candle_pattern
from engine.analysis.chart_patterns import detect_chart_patterns
from engine.analysis.key_levels import detect_key_levels
from engine.analysis.trend_strength import calc_adx_filter
from engine.analysis.volume_profile import calc_volume_profile
from engine.analysis.bollinger import calc_bb_position
from engine.analysis.pullback import calc_pullback_quality
from engine.analysis.confidence import calc_confidence_v2
from engine.analysis.smc import detect_smc
from engine.analysis.cross_exchange import (
    lead_lag_score,
    kimchi_premium,
    execution_gap_pct,
    summarize_cross_exchange,
)
from engine.analysis.exchange_dominance import analyze_exchange_dominance
from engine.analysis.mtf_confluence import calc_mtf_confluence
from engine.analysis.confluence import calc_confluence_score

__all__ = [
    "build_context",
    "detect_market_structure",
    "detect_candle_pattern",
    "detect_chart_patterns",
    "detect_key_levels",
    "calc_adx_filter",
    "calc_volume_profile",
    "calc_bb_position",
    "calc_pullback_quality",
    "calc_confidence_v2",
    "detect_smc",
    "lead_lag_score",
    "kimchi_premium",
    "execution_gap_pct",
    "summarize_cross_exchange",
    "analyze_exchange_dominance",
    "calc_mtf_confluence",
    "calc_confluence_score",
]


def build_context(df: pd.DataFrame) -> dict:
    """심볼당 1회 호출. 모든 분석 결과를 dict로 반환.

    총 성능: ~9ms/심볼 (50ms 예산 내)
    """
    return {
        "structure": detect_market_structure(df),
        "candle": detect_candle_pattern(df),
        "key_levels": detect_key_levels(df),
        "adx": calc_adx_filter(df),
        "volume": calc_volume_profile(df),
        "bb": calc_bb_position(df),
        "pullback": calc_pullback_quality(df),
        "smc": detect_smc(df),
        "chart_patterns": detect_chart_patterns(df),
    }

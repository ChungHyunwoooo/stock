"""engine.analysis — 방향 판단 + 신호 종합.

indicators(수치) → patterns(구조 인식) → analysis(방향 판단)

패턴 탐지는 engine.patterns로 이동.
이 모듈은 판단/종합만 담당.
"""

import pandas as pd

from engine.patterns import (
    detect_market_structure,
    detect_candle_pattern,
    detect_chart_patterns,
    detect_key_levels,
    calc_volume_profile,
    calc_pullback_quality,
    detect_smc,
    calc_adx_filter,
    calc_bb_position,
)
from engine.analysis.direction import calc_confidence_v2, judge_direction
from engine.analysis.confluence import calc_confluence_score
from engine.analysis.mtf_confluence import calc_mtf_confluence
from engine.analysis.cross_exchange import (
    lead_lag_score,
    kimchi_premium,
    execution_gap_pct,
    summarize_cross_exchange,
)
from engine.analysis.exchange_dominance import analyze_exchange_dominance

__all__ = [
    "build_context",
    "judge_direction",
    "calc_confidence_v2",
    "detect_market_structure",
    "detect_candle_pattern",
    "detect_chart_patterns",
    "detect_key_levels",
    "calc_volume_profile",
    "calc_pullback_quality",
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
    """심볼당 1회 호출. 모든 분석 결과를 dict로 반환."""
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

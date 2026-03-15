"""레짐 필터 — ADX 기반 시장 상태 분류 + 전략 자동 전환.

레짐:
  - TRENDING:  ADX >= 25 → BB Squeeze, Triple EMA 활성
  - RANGING:   ADX < 25  → BB Bounce RSI 활성
  - VOLATILE:  ATR percentile > 0.8 → 포지션 축소

전략 라우터가 현재 레짐을 확인하고 적합한 전략만 실행.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
import talib

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


@dataclass(slots=True)
class RegimeResult:
    """레짐 판단 결과."""
    regime: Regime
    adx: float
    atr_pctile: float
    trend_direction: str  # "BULL" | "BEAR" | "NEUTRAL"
    strategies: list[str]  # 활성화할 전략 목록


# 레짐별 활성 전략
_REGIME_STRATEGIES = {
    Regime.TRENDING: ["ema_crossover", "bb_squeeze", "triple_ema"],
    Regime.RANGING: ["bb_bounce_rsi"],
    Regime.VOLATILE: ["ema_crossover"],  # 축소 모드
}


def detect_regime(
    df: pd.DataFrame,
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    atr_period: int = 14,
    atr_lookback: int = 100,
    volatility_threshold: float = 0.8,
) -> RegimeResult:
    """현재 시장 레짐 판단.

    Args:
        df: OHLCV DataFrame
        adx_period: ADX 기간
        adx_threshold: 추세/횡보 기준 ADX
        atr_period: ATR 기간
        atr_lookback: ATR percentile 계산용 lookback
        volatility_threshold: 고변동성 판단 기준 percentile

    Returns:
        RegimeResult
    """
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    close = df["close"].values.astype(np.float64)

    # ADX
    adx_vals = talib.ADX(high, low, close, timeperiod=adx_period)
    current_adx = float(adx_vals[-1]) if not np.isnan(adx_vals[-1]) else 0

    # ATR percentile
    atr_vals = talib.ATR(high, low, close, timeperiod=atr_period)
    current_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0
    window = atr_vals[-atr_lookback:]
    valid = window[~np.isnan(window)]
    atr_pctile = float(np.sum(valid < current_atr)) / max(len(valid) - 1, 1) if len(valid) > 1 else 0.5

    # +DI / -DI 방향
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=adx_period)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=adx_period)
    pdi = float(plus_di[-1]) if not np.isnan(plus_di[-1]) else 0
    mdi = float(minus_di[-1]) if not np.isnan(minus_di[-1]) else 0

    if pdi > mdi:
        direction = "BULL"
    elif mdi > pdi:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    # 레짐 결정
    if atr_pctile >= volatility_threshold:
        regime = Regime.VOLATILE
    elif current_adx >= adx_threshold:
        regime = Regime.TRENDING
    else:
        regime = Regime.RANGING

    return RegimeResult(
        regime=regime,
        adx=round(current_adx, 2),
        atr_pctile=round(atr_pctile, 4),
        trend_direction=direction,
        strategies=_REGIME_STRATEGIES[regime],
    )


def is_strategy_allowed(strategy_name: str, regime: RegimeResult) -> bool:
    """해당 전략이 현재 레짐에서 허용되는지 확인."""
    return strategy_name in regime.strategies


# ---------------------------------------------------------------------------
# 불가능 조합 validation — 전략 설계 시 사전 차단
# ---------------------------------------------------------------------------

# 전략 태그 정의 (전략 definition.json의 tags 필드와 매핑)
# strategy_type: trend_following, mean_reversion, breakout, structural, orderflow, scalping, divergence
# timeframe: 1m, 5m, 15m, 1h, 4h, 1d, 1w
# entry_type: breakout, pullback, reversal, crossover, structural
# data_level: L1(ohlcv), L2(+volume), L3(+derivatives), L4(+cross_exchange)

@dataclass(slots=True)
class StrategyConstraint:
    """불가능 조합 규칙."""
    field: str       # 검사 대상 필드
    value: str       # 해당 값
    forbidden_field: str  # 금지 대상 필드
    forbidden_value: str  # 금지 값
    reason: str      # 사유

# 룰 테이블: 조합 불가 규칙
FORBIDDEN_COMBINATIONS: list[StrategyConstraint] = [
    # 국면 × 전략유형
    StrategyConstraint("regime", "RANGING", "strategy_type", "trend_following",
                       "횡보장에서 추세추종은 연속 휩소 손실"),
    StrategyConstraint("regime", "TRENDING", "strategy_type", "mean_reversion",
                       "강한 추세에서 역추세 진입은 떨어지는 칼날"),
    StrategyConstraint("regime", "VOLATILE", "strategy_type", "scalping",
                       "고변동성에서 스캘핑은 슬리피지로 SL 무력화"),
    # 시간축 × 전략유형
    StrategyConstraint("timeframe", "1m", "requires", "regime_filter",
                       "1분봉에서 레짐 판별은 노이즈만 반영"),
    StrategyConstraint("timeframe", "5m", "requires", "regime_filter",
                       "5분봉에서 레짐 판별은 노이즈만 반영"),
    StrategyConstraint("timeframe", "1m", "requires", "chart_patterns",
                       "1분봉에서 대형 차트패턴은 무의미"),
    # 시간축 × 복잡도
    StrategyConstraint("timeframe", "1m", "max_indicators", "6",
                       "스캘핑에 6+ 지표는 신호 지연 > 기회 수명"),
    StrategyConstraint("timeframe", "1w", "min_indicators", "1",
                       "주봉 포지션을 단일 지표로 운영은 리스크 관리 부재"),
    # 국면 × 진입로직
    StrategyConstraint("regime", "RANGING", "entry_type", "breakout",
                       "횡보 확정 후 돌파 기대는 모순"),
    StrategyConstraint("regime", "RANGING", "entry_type", "pullback",
                       "추세 없이 눌림목 진입은 횡보 진동과 구분 불가"),
    # 데이터 × 전략유형
    StrategyConstraint("data_level", "L1", "strategy_type", "orderflow",
                       "OHLCV만으로 오더플로우 판단 불가"),
    StrategyConstraint("data_level", "L1", "strategy_type", "funding_arb",
                       "펀딩비 데이터 없이 펀딩 차익 불가"),
]


def validate_strategy_combination(tags: dict[str, str]) -> list[str]:
    """전략 태그 조합의 불가능 규칙 위반 검사.

    Args:
        tags: 전략 메타 태그 dict
              예: {"strategy_type": "trend_following", "timeframe": "4h",
                   "entry_type": "pullback", "data_level": "L2", ...}

    Returns:
        위반 사유 목록 (빈 리스트면 통과)
    """
    violations: list[str] = []
    for rule in FORBIDDEN_COMBINATIONS:
        if tags.get(rule.field) == rule.value and tags.get(rule.forbidden_field) == rule.forbidden_value:
            violations.append(
                f"[{rule.field}={rule.value}] + [{rule.forbidden_field}={rule.forbidden_value}]: {rule.reason}"
            )
    return violations


def validate_regime_strategy(regime: RegimeResult, tags: dict[str, str]) -> list[str]:
    """현재 레짐과 전략 태그의 실시간 호환성 검사.

    detect_regime() 결과와 전략 태그를 받아 런타임에서 검증.

    Returns:
        위반 사유 목록 (빈 리스트면 통과)
    """
    runtime_tags = {**tags, "regime": regime.regime.value}
    return validate_strategy_combination(runtime_tags)

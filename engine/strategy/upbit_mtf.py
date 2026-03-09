"""Multi-Timeframe (MTF) 추세 분석.

15분/1시간봉으로 상위 추세를 판단하고,
5분봉 진입 시그널과 방향이 일치하는지 필터링한다.

추세 판단: EMA 9/21 + RSI + 가격 위치
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
import talib

logger = logging.getLogger(__name__)


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class TimeframeTrend:
    """단일 타임프레임 추세 분석 결과."""
    interval: str
    direction: TrendDirection
    strength: float  # 0.0 ~ 1.0
    ema_fast: float
    ema_slow: float
    rsi: float
    price: float
    detail: str

    def to_dict(self) -> dict:
        return {
            "interval": self.interval,
            "direction": self.direction.value,
            "strength": round(self.strength, 2),
            "ema_fast": round(self.ema_fast, 2),
            "ema_slow": round(self.ema_slow, 2),
            "rsi": round(self.rsi, 1),
            "price": self.price,
            "detail": self.detail,
        }


@dataclass
class TrendContext:
    """15분 + 1시간 + 일봉 + 주봉 종합 추세 컨텍스트."""
    tf_15m: TimeframeTrend | None = None
    tf_1h: TimeframeTrend | None = None
    tf_1d: TimeframeTrend | None = None   # 일봉 추세 (사이클 필터)
    tf_1w: TimeframeTrend | None = None   # 주봉 추세 (light filter)

    def allows_long(self) -> bool:
        """LONG 허용: 추세가 BEARISH가 아니면 허용."""
        # 15m/1h: 기존 로직 (primary filter)
        for tf in [self.tf_15m, self.tf_1h]:
            if tf and tf.direction == TrendDirection.BEARISH and tf.strength > 0.6:
                return False
        # 1d: strength > 0.6이면 역방향 차단
        if self.tf_1d and self.tf_1d.direction == TrendDirection.BEARISH and self.tf_1d.strength > 0.6:
            return False
        # 1w: 차단하지 않음 (soft penalty만 — confidence_boost에서 처리)
        return True

    def allows_short(self) -> bool:
        """SHORT 허용: 추세가 BULLISH가 아니면 허용."""
        for tf in [self.tf_15m, self.tf_1h]:
            if tf and tf.direction == TrendDirection.BULLISH and tf.strength > 0.6:
                return False
        if self.tf_1d and self.tf_1d.direction == TrendDirection.BULLISH and self.tf_1d.strength > 0.6:
            return False
        return True

    def confidence_boost(self) -> float:
        """MTF 정렬도에 따른 신뢰도 배율.

        - 15m + 1h 모두 같은 방향 → 1.3x
        - 한쪽만 일치 또는 NEUTRAL → 1.0x
        - 역방향 포함 → 0.7x
        - tf_1d 순방향 → 추가 1.2x boost
        - tf_1w 역방향 (strength > 0.7) → 0.8x soft penalty
        """
        directions = []
        for tf in [self.tf_15m, self.tf_1h]:
            if tf:
                directions.append(tf.direction)

        if not directions:
            return 1.0

        bullish_count = sum(1 for d in directions if d == TrendDirection.BULLISH)
        bearish_count = sum(1 for d in directions if d == TrendDirection.BEARISH)

        if bullish_count == len(directions) or bearish_count == len(directions):
            boost = 1.3  # All aligned
        elif bullish_count > 0 and bearish_count > 0:
            boost = 0.7  # Conflicting
        else:
            boost = 1.0  # Mixed with neutral

        # 일봉 사이클 boost: 순방향이면 1.2x
        if self.tf_1d and self.tf_1d.strength > 0.6:
            dominant = self.dominant_direction
            if self.tf_1d.direction == dominant and dominant != TrendDirection.NEUTRAL:
                boost *= 1.2

        # 주봉 사이클 soft penalty: 역방향이면 0.8x
        if self.tf_1w and self.tf_1w.strength > 0.7:
            dominant = self.dominant_direction
            if (dominant == TrendDirection.BULLISH and self.tf_1w.direction == TrendDirection.BEARISH) or \
               (dominant == TrendDirection.BEARISH and self.tf_1w.direction == TrendDirection.BULLISH):
                boost *= 0.8

        return round(boost, 2)

    @property
    def dominant_direction(self) -> TrendDirection:
        """지배적 추세 방향."""
        directions = []
        for tf in [self.tf_15m, self.tf_1h]:
            if tf:
                directions.append(tf.direction)

        if not directions:
            return TrendDirection.NEUTRAL

        bullish_count = sum(1 for d in directions if d == TrendDirection.BULLISH)
        bearish_count = sum(1 for d in directions if d == TrendDirection.BEARISH)

        if bullish_count > bearish_count:
            return TrendDirection.BULLISH
        elif bearish_count > bullish_count:
            return TrendDirection.BEARISH
        return TrendDirection.NEUTRAL

    def summary(self) -> str:
        """MTF 요약 문자열."""
        parts = []
        if self.tf_15m:
            parts.append(f"15m={self.tf_15m.direction.value}")
        if self.tf_1h:
            parts.append(f"1h={self.tf_1h.direction.value}")
        if self.tf_1d:
            parts.append(f"1d={self.tf_1d.direction.value}")
        if self.tf_1w:
            parts.append(f"1w={self.tf_1w.direction.value}")
        if not parts:
            return "MTF: N/A"
        return f"MTF: {', '.join(parts)}"

    def to_dict(self) -> dict:
        return {
            "15m": self.tf_15m.to_dict() if self.tf_15m else None,
            "1h": self.tf_1h.to_dict() if self.tf_1h else None,
            "1d": self.tf_1d.to_dict() if self.tf_1d else None,
            "1w": self.tf_1w.to_dict() if self.tf_1w else None,
            "dominant": self.dominant_direction.value,
            "confidence_boost": self.confidence_boost(),
            "allows_long": self.allows_long(),
            "allows_short": self.allows_short(),
        }


def analyze_timeframe(
    df: pd.DataFrame,
    interval: str,
    ema_fast_period: int = 9,
    ema_slow_period: int = 21,
    rsi_period: int = 14,
) -> TimeframeTrend | None:
    """단일 타임프레임 추세 분석.

    EMA 9/21 위치 + RSI + 가격 위치로 방향 + 강도를 판단한다.
    """
    if df is None or len(df) < max(ema_slow_period, rsi_period) + 5:
        return None

    close = df["close"].values

    try:
        ema_fast = talib.EMA(close, timeperiod=ema_fast_period)
        ema_slow = talib.EMA(close, timeperiod=ema_slow_period)
        rsi = talib.RSI(close, timeperiod=rsi_period)
    except Exception as e:
        logger.warning("Indicator calc failed for %s: %s", interval, e)
        return None

    if ema_fast.size == 0 or ema_slow.size == 0 or rsi.size == 0:
        return None

    last_ema_fast = float(ema_fast[-1])
    last_ema_slow = float(ema_slow[-1])
    last_rsi = float(rsi[-1])

    if np.isnan(last_ema_fast) or np.isnan(last_ema_slow) or np.isnan(last_rsi):
        return None

    curr_price = float(close[-1])
    curr_ema_fast = last_ema_fast
    curr_ema_slow = last_ema_slow
    curr_rsi = last_rsi

    # EMA spread (normalized)
    ema_spread = (curr_ema_fast - curr_ema_slow) / curr_price * 100

    # Scoring system
    score = 0.0  # -1.0 (strong bearish) to +1.0 (strong bullish)

    # 1. EMA position (weight: 40%)
    if curr_ema_fast > curr_ema_slow:
        score += 0.4 * min(1.0, abs(ema_spread) * 5)
    else:
        score -= 0.4 * min(1.0, abs(ema_spread) * 5)

    # 2. Price vs EMA (weight: 30%)
    if curr_price > curr_ema_fast > curr_ema_slow:
        score += 0.3
    elif curr_price < curr_ema_fast < curr_ema_slow:
        score -= 0.3
    elif curr_price > curr_ema_slow:
        score += 0.15
    elif curr_price < curr_ema_slow:
        score -= 0.15

    # 3. RSI (weight: 30%)
    if curr_rsi > 60:
        score += 0.3 * min(1.0, (curr_rsi - 50) / 30)
    elif curr_rsi < 40:
        score -= 0.3 * min(1.0, (50 - curr_rsi) / 30)

    # Determine direction and strength
    strength = abs(score)
    if score > 0.15:
        direction = TrendDirection.BULLISH
    elif score < -0.15:
        direction = TrendDirection.BEARISH
    else:
        direction = TrendDirection.NEUTRAL

    # Build detail string
    ema_status = "EMA9>21" if curr_ema_fast > curr_ema_slow else "EMA9<21"
    price_pos = "상단" if curr_price > curr_ema_slow else "하단"
    detail = f"{ema_status}, RSI={curr_rsi:.0f}, 가격 EMA{ema_slow_period} {price_pos}"

    return TimeframeTrend(
        interval=interval,
        direction=direction,
        strength=round(strength, 2),
        ema_fast=curr_ema_fast,
        ema_slow=curr_ema_slow,
        rsi=curr_rsi,
        price=curr_price,
        detail=detail,
    )


def analyze_mtf(
    df_15m: pd.DataFrame | None,
    df_1h: pd.DataFrame | None,
    df_1d: pd.DataFrame | None = None,
    df_1w: pd.DataFrame | None = None,
) -> TrendContext:
    """멀티타임프레임 종합 추세 분석.

    15분봉 + 1시간봉 + (선택) 일봉/주봉 데이터로 TrendContext를 생성한다.
    """
    ctx = TrendContext()

    if df_15m is not None:
        ctx.tf_15m = analyze_timeframe(df_15m, "15m")

    if df_1h is not None:
        ctx.tf_1h = analyze_timeframe(df_1h, "1h")

    if df_1d is not None and len(df_1d) >= 20:
        ctx.tf_1d = analyze_timeframe(df_1d, "1d")

    if df_1w is not None and len(df_1w) >= 10:
        ctx.tf_1w = analyze_timeframe(df_1w, "1w")

    return ctx


def mtf_filter_signal(
    signal_side: str,
    trend_ctx: TrendContext,
) -> tuple[bool, float, str]:
    """MTF 필터: 시그널 방향과 추세 일치 여부 확인.

    일봉: strength > 0.6이면 역방향 차단, 순방향 boost 1.2x
    주봉: strength > 0.7이면 역방향 confidence 0.8x (차단하지 않음, soft penalty)

    Returns:
        (allowed, confidence_multiplier, mtf_reason)
    """
    if signal_side == "LONG":
        allowed = trend_ctx.allows_long()
    else:
        allowed = trend_ctx.allows_short()

    boost = trend_ctx.confidence_boost()
    reason = trend_ctx.summary()

    if not allowed:
        # 어떤 타임프레임이 차단했는지 표시
        blockers = []
        if signal_side == "LONG":
            for label, tf in [("1h", trend_ctx.tf_1h), ("15m", trend_ctx.tf_15m), ("1d", trend_ctx.tf_1d)]:
                if tf and tf.direction == TrendDirection.BEARISH and tf.strength > 0.6:
                    blockers.append(label)
        else:
            for label, tf in [("1h", trend_ctx.tf_1h), ("15m", trend_ctx.tf_15m), ("1d", trend_ctx.tf_1d)]:
                if tf and tf.direction == TrendDirection.BULLISH and tf.strength > 0.6:
                    blockers.append(label)
        blocker_str = "+".join(blockers) if blockers else trend_ctx.dominant_direction.value
        reason += f" [차단: {signal_side} vs {blocker_str}]"

    return allowed, boost, reason

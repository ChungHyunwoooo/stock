"""수박지표 보조 신호 필터.

수박지표 특성:
  - D1 기준 EMA+StdDev 바닥 축적 감지
  - 2년간 15건 수준으로 빈도 매우 낮음
  - 독립 운용 불가, LONG 보조 확신도 부스터로 사용

통합 방식:
  - 수박지표 활성 시 LONG 패턴 신호의 확신도(confidence)를 상향
  - LONG 패턴이 없으면 수박지표 단독으로 신호 생성하지 않음
  - SHORT 패턴에는 영향 없음
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from engine.indicators.custom import watermelon_indicator

logger = logging.getLogger(__name__)


def is_watermelon_active(df_1d: pd.DataFrame) -> bool:
    """현재 D1 기준 수박지표 활성 여부.

    shell > 0 이고 melon/shell 비율이 0.7 이상이면 축적 완료 근접.
    """
    if df_1d is None or len(df_1d) < 500:
        return False

    try:
        result = watermelon_indicator(df_1d)
        shell = result["shell"]
        melon = result["melon"]

        last_shell = float(shell.iloc[-1])
        last_melon = float(melon.iloc[-1])

        if last_shell <= 0:
            return False

        fill_ratio = last_melon / last_shell if last_shell > 0 else 0.0
        active = fill_ratio >= 0.7

        if active:
            logger.info(
                "수박지표 활성: shell=%.2f, melon=%.2f, fill=%.1f%%",
                last_shell, last_melon, fill_ratio * 100,
            )
        return active

    except Exception as e:
        logger.warning("수박지표 계산 실패: %s", e)
        return False


def apply_watermelon_boost(
    confidence: float,
    watermelon_active: bool,
    boost: float = 0.2,
) -> float:
    """수박지표 활성 시 확신도 부스트 적용.

    Args:
        confidence: 현재 확신도 (0.0 ~ 1.0)
        watermelon_active: 수박지표 활성 여부
        boost: 부스트 값 (기본 0.2)

    Returns:
        조정된 확신도 (최대 1.0)
    """
    if watermelon_active:
        return min(1.0, confidence + boost)
    return confidence

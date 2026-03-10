"""ROC(변화율) 및 Momentum 인디케이터."""

from __future__ import annotations

import talib

from engine.indicators.base import Array, SingleResult, _to_numpy


def roc(close: Array, period: int = 10) -> SingleResult:
    """ROC(Rate of Change) 계산. 단위: %."""
    c = _to_numpy(close)
    values = talib.ROC(c, timeperiod=period)
    return SingleResult.from_array(values)


def momentum(close: Array, period: int = 10) -> SingleResult:
    """Momentum 계산 (절대값 차이)."""
    c = _to_numpy(close)
    values = talib.MOM(c, timeperiod=period)
    return SingleResult.from_array(values)


def describe() -> dict:
    """ROC/Momentum 인디케이터 메타데이터."""
    return {
        "name": "ROC",
        "full_name": "Rate of Change",
        "default_period": 10,
        "outputs": ["ROC (%)", "Momentum (abs)"],
        "description": "ROC: 기간 대비 변화율(%), MOM: 기간 대비 절대 변화량",
    }

"""수박지표 (Watermelon) — EMA+StdDev 기반 매집 완성도 시각화."""

from __future__ import annotations

import pandas as pd


def watermelon(
    df: pd.DataFrame,
    ema_period: int = 26,
    std_period: int = 26,
    std_mult: float = 2.5,
    shift_period: int = 25,
    scale1: float = 7.5,
    scale2: float = 4.5,
    support_period: int = 112,
    mid_period: int = 224,
    long_period: int = 448,
    ema_gap_pct: float = 1.0,
    short_gap_pct: float = 15.0,
    fortress_period: int = 5,
) -> dict[str, pd.Series]:
    """수박지표 계산.

    Returns:
        dict with keys: shell (껍질), melon (수박)
        shell이 melon으로 채워지면 매집 완성 근접.
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    ema_short = c.ewm(span=ema_period, adjust=False).mean()
    typical = (c + h + lo) / 3
    std = typical.rolling(std_period).std()
    n1 = (ema_short + std_mult * std).shift(shift_period) / scale1

    ema_sup = c.ewm(span=support_period, adjust=False).mean()
    ema_mid = c.ewm(span=mid_period, adjust=False).mean()
    ema_lng = c.ewm(span=long_period, adjust=False).mean()
    ema_fort = c.ewm(span=fortress_period, adjust=False).mean()

    ga = (
        (ema_sup * (100 + ema_gap_pct) / 100 < ema_mid)
        & (ema_mid * (100 + ema_gap_pct) / 100 < ema_lng)
        & (ema_mid * (100 + short_gap_pct) / 100 >= c)
        & (ema_sup < ema_fort)
    )

    active = ema_sup <= c

    shell = pd.Series(0.0, index=df.index)
    shell[ga & active] = n1[ga & active]

    val = h / scale1
    inner = val.copy()
    inner[n1 < val] = (h / scale2)[n1 < val]

    melon = pd.Series(0.0, index=df.index)
    melon[ga & active] = inner[ga & active]

    return {"shell": shell, "melon": melon}


# registry 호환 래퍼
watermelon_indicator = watermelon


def fill_ratio(df: pd.DataFrame) -> float:
    """현재 수박 채움 비율 (melon/shell). 1.0에 가까울수록 매집 완성."""
    result = watermelon(df)
    s = float(result["shell"].iloc[-1])
    m = float(result["melon"].iloc[-1])
    if s == 0:
        return 0.0
    return min(m / s, 1.0)


def is_accumulating(df: pd.DataFrame) -> bool:
    """현재 매집 구간인지 (shell > 0)."""
    result = watermelon(df)
    return float(result["shell"].iloc[-1]) > 0


def describe() -> dict:
    return {
        "name": "수박지표",
        "name_en": "Watermelon",
        "category": "custom",
        "params": {
            "ema_period": 26, "std_period": 26, "std_mult": 2.5,
            "shift_period": 25, "scale1": 7.5, "scale2": 4.5,
            "support_period": 112, "mid_period": 224, "long_period": 448,
        },
        "outputs": ["shell", "melon"],
        "interpretation": "shell(껍질) 안에 melon(수박)이 차오르면 매집 완성 근접. LONG 보조 신호.",
    }

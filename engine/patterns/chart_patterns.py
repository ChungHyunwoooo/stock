"""차트 패턴 인식 — Double Top/Bottom, Head&Shoulders, Cup&Handle, Triangle, Flag, Wedge.

스윙 고점/저점(5-bar pivot) 기반 클래식 차트 패턴 감지.
의존성: numpy, pandas (talib 불필요)
성능: ~3ms
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

@dataclass(frozen=True, slots=True)
class ChartPattern:
    name: str
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: float  # 0.0 - 1.0
    description: str
    key_prices: dict = field(default_factory=dict)

def detect_chart_patterns(df: pd.DataFrame, lookback: int = 120) -> list[ChartPattern]:
    """OHLCV DataFrame에서 클래식 차트 패턴을 감지.

    Returns:
        감지된 ChartPattern 리스트 (confidence 내림차순 정렬)
    """
    if len(df) < lookback:
        lookback = len(df)
    if lookback < 30:
        return []

    high = df["high"].values[-lookback:].astype(float)
    low = df["low"].values[-lookback:].astype(float)
    close = df["close"].values[-lookback:].astype(float)

    swing_highs, swing_lows = _find_swings(high, low)
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return []

    curr_price = float(close[-1])
    atr = _calc_atr(high, low, close)

    patterns: list[ChartPattern] = []

    for detector in [
        _detect_double_top,
        _detect_double_bottom,
        _detect_head_and_shoulders,
        _detect_inverse_head_and_shoulders,
        _detect_cup_and_handle,
        _detect_ascending_triangle,
        _detect_descending_triangle,
        _detect_bull_flag,
        _detect_bear_flag,
        _detect_rising_wedge,
        _detect_falling_wedge,
    ]:
        result = detector(swing_highs, swing_lows, high, low, close, curr_price, atr)
        if result is not None:
            patterns.append(result)

    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns

# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------

def _find_swings(
    high: np.ndarray, low: np.ndarray,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """5-bar pivot 스윙 고점/저점 감지."""
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(2, len(high) - 2):
        if (high[i] > high[i - 1] and high[i] > high[i - 2]
                and high[i] > high[i + 1] and high[i] > high[i + 2]):
            swing_highs.append((i, float(high[i])))

        if (low[i] < low[i - 1] and low[i] < low[i - 2]
                and low[i] < low[i + 1] and low[i] < low[i + 2]):
            swing_lows.append((i, float(low[i])))

    return swing_highs, swing_lows

def _calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """간이 ATR 계산."""
    n = len(high)
    if n < period + 1:
        return float(np.mean(high - low))
    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
    tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))
    return float(np.mean(tr[-period:]))

def _price_near(a: float, b: float, tolerance_pct: float = 0.02) -> bool:
    """두 가격이 tolerance_pct 이내인지 확인."""
    if b == 0:
        return False
    return abs(a - b) / b < tolerance_pct

# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

def _detect_double_top(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """더블탑: 두 고점이 비슷한 가격, 사이에 저점(neckline)."""
    if len(swing_highs) < 2:
        return None

    h1_idx, h1 = swing_highs[-2]
    h2_idx, h2 = swing_highs[-1]

    if not _price_near(h1, h2, 0.025):
        return None
    if h2_idx - h1_idx < 5:
        return None

    # 두 고점 사이 저점 찾기
    between_lows = [(i, p) for i, p in swing_lows if h1_idx < i < h2_idx]
    if not between_lows:
        return None

    neckline = min(between_lows, key=lambda x: x[1])[1]

    # 현재가가 neckline 근처 또는 아래
    if curr_price > h2 * 0.98:
        return None

    conf = 0.5
    if curr_price < neckline:
        conf += 0.2
    similarity = 1.0 - abs(h1 - h2) / max(h1, h2)
    conf += similarity * 0.2
    depth = (max(h1, h2) - neckline) / max(h1, h2)
    if depth > 0.03:
        conf += 0.1

    return ChartPattern(
        name="Double Top",
        direction="BEARISH",
        confidence=min(conf, 1.0),
        description=f"이중천장 — 두 고점 {h1:,.0f} / {h2:,.0f}, 넥라인 {neckline:,.0f}",
        key_prices={"peak1": h1, "peak2": h2, "neckline": neckline},
    )

def _detect_double_bottom(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """더블바텀: 두 저점이 비슷한 가격, 사이에 고점(neckline)."""
    if len(swing_lows) < 2:
        return None

    l1_idx, l1 = swing_lows[-2]
    l2_idx, l2 = swing_lows[-1]

    if not _price_near(l1, l2, 0.025):
        return None
    if l2_idx - l1_idx < 5:
        return None

    between_highs = [(i, p) for i, p in swing_highs if l1_idx < i < l2_idx]
    if not between_highs:
        return None

    neckline = max(between_highs, key=lambda x: x[1])[1]

    if curr_price < l2 * 1.02:
        return None

    conf = 0.5
    if curr_price > neckline:
        conf += 0.2
    similarity = 1.0 - abs(l1 - l2) / max(l1, l2)
    conf += similarity * 0.2
    depth = (neckline - min(l1, l2)) / neckline
    if depth > 0.03:
        conf += 0.1

    return ChartPattern(
        name="Double Bottom",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=f"이중바닥 — 두 저점 {l1:,.0f} / {l2:,.0f}, 넥라인 {neckline:,.0f}",
        key_prices={"trough1": l1, "trough2": l2, "neckline": neckline},
    )

def _detect_head_and_shoulders(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """헤드앤숄더: 세 고점 중 가운데가 최고, 양쪽 어깨가 비슷."""
    if len(swing_highs) < 3:
        return None

    ls_idx, ls = swing_highs[-3]  # left shoulder
    h_idx, h = swing_highs[-2]    # head
    rs_idx, rs = swing_highs[-1]  # right shoulder

    if not (h > ls and h > rs):
        return None
    if not _price_near(ls, rs, 0.04):
        return None

    # 넥라인: head 양쪽 저점
    left_lows = [(i, p) for i, p in swing_lows if ls_idx < i < h_idx]
    right_lows = [(i, p) for i, p in swing_lows if h_idx < i < rs_idx]
    if not left_lows or not right_lows:
        return None

    nl_left = min(left_lows, key=lambda x: x[1])[1]
    nl_right = min(right_lows, key=lambda x: x[1])[1]
    neckline = (nl_left + nl_right) / 2

    conf = 0.5
    shoulder_sym = 1.0 - abs(ls - rs) / max(ls, rs)
    conf += shoulder_sym * 0.2
    if curr_price < neckline:
        conf += 0.2
    head_prominence = (h - max(ls, rs)) / h
    if head_prominence > 0.02:
        conf += 0.1

    return ChartPattern(
        name="Head & Shoulders",
        direction="BEARISH",
        confidence=min(conf, 1.0),
        description=f"헤드앤숄더 — 좌 {ls:,.0f} / 헤드 {h:,.0f} / 우 {rs:,.0f}, 넥라인 {neckline:,.0f}",
        key_prices={"left_shoulder": ls, "head": h, "right_shoulder": rs, "neckline": neckline},
    )

def _detect_inverse_head_and_shoulders(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """역헤드앤숄더: 세 저점 중 가운데가 최저, 양쪽 어깨가 비슷."""
    if len(swing_lows) < 3:
        return None

    ls_idx, ls = swing_lows[-3]
    h_idx, h = swing_lows[-2]
    rs_idx, rs = swing_lows[-1]

    if not (h < ls and h < rs):
        return None
    if not _price_near(ls, rs, 0.04):
        return None

    left_highs = [(i, p) for i, p in swing_highs if ls_idx < i < h_idx]
    right_highs = [(i, p) for i, p in swing_highs if h_idx < i < rs_idx]
    if not left_highs or not right_highs:
        return None

    nl_left = max(left_highs, key=lambda x: x[1])[1]
    nl_right = max(right_highs, key=lambda x: x[1])[1]
    neckline = (nl_left + nl_right) / 2

    conf = 0.5
    shoulder_sym = 1.0 - abs(ls - rs) / max(ls, rs)
    conf += shoulder_sym * 0.2
    if curr_price > neckline:
        conf += 0.2
    head_prominence = (min(ls, rs) - h) / min(ls, rs)
    if head_prominence > 0.02:
        conf += 0.1

    return ChartPattern(
        name="Inverse Head & Shoulders",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=f"역헤드앤숄더 — 좌 {ls:,.0f} / 헤드 {h:,.0f} / 우 {rs:,.0f}, 넥라인 {neckline:,.0f}",
        key_prices={"left_shoulder": ls, "head": h, "right_shoulder": rs, "neckline": neckline},
    )

def _detect_cup_and_handle(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """컵앤핸들: U자형 회복 후 작은 조정(핸들).

    최소 3개 저점이 U자형을 이루고, 이후 소폭 조정.
    """
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return None

    # 최근 스윙 고점 중 비슷한 높이의 두 고점(컵 림) 찾기
    rim_candidates = []
    for i in range(len(swing_highs) - 1):
        for j in range(i + 1, len(swing_highs)):
            h1_idx, h1 = swing_highs[i]
            h2_idx, h2 = swing_highs[j]
            if _price_near(h1, h2, 0.03) and h2_idx - h1_idx >= 10:
                rim_candidates.append((i, j, h1_idx, h2_idx, h1, h2))

    if not rim_candidates:
        return None

    # 가장 최근 후보 사용
    _, _, rim1_idx, rim2_idx, rim1, rim2 = rim_candidates[-1]
    rim_level = (rim1 + rim2) / 2

    # 컵 바닥: 두 림 사이의 최저점
    between_lows = [(i, p) for i, p in swing_lows if rim1_idx < i < rim2_idx]
    if not between_lows:
        return None

    cup_bottom_idx, cup_bottom = min(between_lows, key=lambda x: x[1])

    # 컵 깊이 확인 (림 대비 3~40%)
    cup_depth = (rim_level - cup_bottom) / rim_level
    if not (0.03 < cup_depth < 0.40):
        return None

    # U자형 확인: 바닥이 대략 중앙에 위치
    total_width = rim2_idx - rim1_idx
    bottom_position = (cup_bottom_idx - rim1_idx) / total_width
    if not (0.25 < bottom_position < 0.75):
        return None

    # 핸들: 두 번째 림 이후 소폭 조정
    handle_lows = [(i, p) for i, p in swing_lows if i > rim2_idx]
    has_handle = False
    handle_low = rim_level
    if handle_lows:
        handle_low = handle_lows[-1][1]
        handle_depth = (rim_level - handle_low) / rim_level
        if 0.005 < handle_depth < cup_depth * 0.5:
            has_handle = True

    conf = 0.4
    # U자형 대칭성
    conf += (1.0 - abs(bottom_position - 0.5) * 2) * 0.15
    # 림 수평성
    rim_sim = 1.0 - abs(rim1 - rim2) / max(rim1, rim2)
    conf += rim_sim * 0.15
    if has_handle:
        conf += 0.15
    if curr_price > rim_level * 0.97:
        conf += 0.15

    return ChartPattern(
        name="Cup & Handle" if has_handle else "Cup",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=(
            f"컵앤핸들 — 림 {rim_level:,.0f}, 바닥 {cup_bottom:,.0f}, "
            f"깊이 {cup_depth:.1%}"
            + (f", 핸들 저점 {handle_low:,.0f}" if has_handle else "")
        ),
        key_prices={
            "rim_left": rim1, "rim_right": rim2,
            "cup_bottom": cup_bottom, "handle_low": handle_low,
        },
    )

def _detect_ascending_triangle(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """상승삼각형: 수평 저항 + 상승하는 지지."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs[-2:]
    recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows[-2:]

    # 고점들이 수평인지 (비슷한 가격)
    high_prices = [p for _, p in recent_highs]
    high_range = (max(high_prices) - min(high_prices)) / max(high_prices)
    if high_range > 0.025:
        return None

    # 저점들이 상승 중인지
    low_prices = [p for _, p in recent_lows]
    rising_lows = all(low_prices[i] < low_prices[i + 1] for i in range(len(low_prices) - 1))
    if not rising_lows:
        return None

    resistance = sum(high_prices) / len(high_prices)
    last_support = low_prices[-1]

    conf = 0.5
    conf += (1.0 - high_range / 0.025) * 0.2
    if len(recent_highs) >= 3:
        conf += 0.15
    if curr_price > resistance * 0.97:
        conf += 0.15

    return ChartPattern(
        name="Ascending Triangle",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=f"상승삼각형 — 저항 {resistance:,.0f}, 지지 상승 중 {last_support:,.0f}",
        key_prices={"resistance": resistance, "last_support": last_support},
    )

def _detect_descending_triangle(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """하강삼각형: 수평 지지 + 하락하는 저항."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs[-2:]
    recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows[-2:]

    low_prices = [p for _, p in recent_lows]
    low_range = (max(low_prices) - min(low_prices)) / max(low_prices)
    if low_range > 0.025:
        return None

    high_prices = [p for _, p in recent_highs]
    falling_highs = all(high_prices[i] > high_prices[i + 1] for i in range(len(high_prices) - 1))
    if not falling_highs:
        return None

    support = sum(low_prices) / len(low_prices)
    last_resistance = high_prices[-1]

    conf = 0.5
    conf += (1.0 - low_range / 0.025) * 0.2
    if len(recent_lows) >= 3:
        conf += 0.15
    if curr_price < support * 1.03:
        conf += 0.15

    return ChartPattern(
        name="Descending Triangle",
        direction="BEARISH",
        confidence=min(conf, 1.0),
        description=f"하강삼각형 — 지지 {support:,.0f}, 저항 하락 중 {last_resistance:,.0f}",
        key_prices={"support": support, "last_resistance": last_resistance},
    )

def _detect_bull_flag(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """불플래그: 급등 후 소폭 하향 채널 조정."""
    n = len(close)
    if n < 30:
        return None

    # 최근 구간에서 급등 찾기 (flag pole)
    # 최근 스윙 고점 직전까지의 상승률 확인
    if len(swing_highs) < 1 or len(swing_lows) < 2:
        return None

    pole_top_idx, pole_top = swing_highs[-1]
    # pole 시작점: pole_top 전 가장 가까운 저점
    pre_lows = [(i, p) for i, p in swing_lows if i < pole_top_idx]
    if not pre_lows:
        return None

    pole_bottom_idx, pole_bottom = pre_lows[-1]
    pole_gain = (pole_top - pole_bottom) / pole_bottom if pole_bottom > 0 else 0

    if pole_gain < 0.05:  # 최소 5% 상승
        return None

    # flag: pole_top 이후 가격이 소폭 하락 조정 중
    flag_data = close[pole_top_idx:]
    if len(flag_data) < 3:
        return None

    flag_high = float(np.max(high[pole_top_idx:]))
    flag_low = float(np.min(low[pole_top_idx:]))
    flag_range = (flag_high - flag_low) / flag_high
    pole_range = (pole_top - pole_bottom) / pole_top

    # flag 범위가 pole의 50% 이내
    if flag_range > pole_range * 0.5:
        return None

    # flag가 하향 조정인지 (현재가 < pole_top)
    if curr_price > pole_top:
        return None

    # flag 리트레이스먼트
    retrace = (pole_top - curr_price) / (pole_top - pole_bottom)
    if retrace > 0.5:  # 50% 이상 되돌림이면 flag 아님
        return None

    conf = 0.5
    conf += min(pole_gain / 0.15, 1.0) * 0.2  # 큰 pole일수록 확신
    conf += (1.0 - retrace / 0.5) * 0.15
    conf += (1.0 - flag_range / (pole_range * 0.5)) * 0.15

    return ChartPattern(
        name="Bull Flag",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=f"불플래그 — 폴 {pole_bottom:,.0f}->{pole_top:,.0f} (+{pole_gain:.1%}), 조정 {retrace:.0%}",
        key_prices={"pole_bottom": pole_bottom, "pole_top": pole_top, "flag_low": flag_low},
    )

def _detect_bear_flag(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """베어플래그: 급락 후 소폭 상향 채널 조정."""
    n = len(close)
    if n < 30:
        return None

    if len(swing_lows) < 1 or len(swing_highs) < 2:
        return None

    pole_bottom_idx, pole_bottom = swing_lows[-1]
    pre_highs = [(i, p) for i, p in swing_highs if i < pole_bottom_idx]
    if not pre_highs:
        return None

    pole_top_idx, pole_top = pre_highs[-1]
    pole_drop = (pole_top - pole_bottom) / pole_top if pole_top > 0 else 0

    if pole_drop < 0.05:
        return None

    flag_data = close[pole_bottom_idx:]
    if len(flag_data) < 3:
        return None

    flag_high = float(np.max(high[pole_bottom_idx:]))
    flag_low = float(np.min(low[pole_bottom_idx:]))
    flag_range = (flag_high - flag_low) / flag_high
    pole_range = (pole_top - pole_bottom) / pole_top

    if flag_range > pole_range * 0.5:
        return None

    if curr_price < pole_bottom:
        return None

    retrace = (curr_price - pole_bottom) / (pole_top - pole_bottom)
    if retrace > 0.5:
        return None

    conf = 0.5
    conf += min(pole_drop / 0.15, 1.0) * 0.2
    conf += (1.0 - retrace / 0.5) * 0.15
    conf += (1.0 - flag_range / (pole_range * 0.5)) * 0.15

    return ChartPattern(
        name="Bear Flag",
        direction="BEARISH",
        confidence=min(conf, 1.0),
        description=f"베어플래그 — 폴 {pole_top:,.0f}->{pole_bottom:,.0f} (-{pole_drop:.1%}), 반등 {retrace:.0%}",
        key_prices={"pole_top": pole_top, "pole_bottom": pole_bottom, "flag_high": flag_high},
    )

def _detect_rising_wedge(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """상승쐐기: 고점과 저점 모두 상승하지만 수렴."""
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return None

    recent_highs = swing_highs[-3:]
    recent_lows = swing_lows[-3:]

    h_prices = [p for _, p in recent_highs]
    l_prices = [p for _, p in recent_lows]

    # 둘 다 상승
    rising_h = all(h_prices[i] < h_prices[i + 1] for i in range(len(h_prices) - 1))
    rising_l = all(l_prices[i] < l_prices[i + 1] for i in range(len(l_prices) - 1))
    if not (rising_h and rising_l):
        return None

    # 수렴: 고점 기울기 < 저점 기울기 (범위가 좁아짐)
    h_slope = (h_prices[-1] - h_prices[0]) / h_prices[0]
    l_slope = (l_prices[-1] - l_prices[0]) / l_prices[0]

    range_first = h_prices[0] - l_prices[0]
    range_last = h_prices[-1] - l_prices[-1]

    if range_last >= range_first:
        return None

    convergence = 1.0 - range_last / range_first

    conf = 0.4
    conf += min(convergence, 0.5) * 0.4
    if len(recent_highs) >= 3:
        conf += 0.1
    conf += 0.1

    return ChartPattern(
        name="Rising Wedge",
        direction="BEARISH",
        confidence=min(conf, 1.0),
        description=f"상승쐐기 — 수렴도 {convergence:.0%}, 고점 {h_prices[-1]:,.0f}, 저점 {l_prices[-1]:,.0f}",
        key_prices={"high_start": h_prices[0], "high_end": h_prices[-1],
                    "low_start": l_prices[0], "low_end": l_prices[-1]},
    )

def _detect_falling_wedge(
    swing_highs, swing_lows, high, low, close, curr_price, atr,
) -> ChartPattern | None:
    """하락쐐기: 고점과 저점 모두 하락하지만 수렴."""
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return None

    recent_highs = swing_highs[-3:]
    recent_lows = swing_lows[-3:]

    h_prices = [p for _, p in recent_highs]
    l_prices = [p for _, p in recent_lows]

    falling_h = all(h_prices[i] > h_prices[i + 1] for i in range(len(h_prices) - 1))
    falling_l = all(l_prices[i] > l_prices[i + 1] for i in range(len(l_prices) - 1))
    if not (falling_h and falling_l):
        return None

    range_first = h_prices[0] - l_prices[0]
    range_last = h_prices[-1] - l_prices[-1]

    if range_last >= range_first:
        return None

    convergence = 1.0 - range_last / range_first

    conf = 0.4
    conf += min(convergence, 0.5) * 0.4
    if len(recent_highs) >= 3:
        conf += 0.1
    conf += 0.1

    return ChartPattern(
        name="Falling Wedge",
        direction="BULLISH",
        confidence=min(conf, 1.0),
        description=f"하락쐐기 — 수렴도 {convergence:.0%}, 고점 {h_prices[-1]:,.0f}, 저점 {l_prices[-1]:,.0f}",
        key_prices={"high_start": h_prices[0], "high_end": h_prices[-1],
                    "low_start": l_prices[0], "low_end": l_prices[-1]},
    )

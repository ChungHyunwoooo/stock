"""클래식 차트 패턴 백테스트 엔진.

패턴 목록:
  1. Double Bottom (LONG) — 두 저점 유사 + 넥라인 돌파
  2. Double Top (SHORT) — 두 고점 유사 + 넥라인 하향 이탈
  3. Bull Flag (LONG) — 급등 후 하향 수렴 + 상방 돌파
  4. Bear Flag (SHORT) — 급락 후 상향 수렴 + 하방 돌파
  5. Ascending Triangle (LONG) — 수평 저항 + 상승 지지 + 상방 돌파
  6. Descending Triangle (SHORT) — 수평 지지 + 하락 저항 + 하방 돌파

Look-ahead 방지:
  극값은 좌우 order봉만 비교하므로, 극값 k를 사용하려면 k+order < i 이어야 함.
  각 패턴 함수에서 `m < i - order` 필터로 확정된 극값만 사용.

공통 설정:
  타임프레임: 1H
  SL: 패턴 기반 (각 패턴별 상이)
  TP: R:R 비율 적용
  시간제한: 30봉
"""
from __future__ import annotations

import numpy as np
import talib

from engine.backtest.strategy_base import (
    StrategyResult,
    StrategyTrade,
    calc_metrics,
    detect_regime,
    get_start_idx,
    load_ohlcv,
)


# ---------------------------------------------------------------------------
# 로컬 극값 탐지 (전체 배열 1회 계산, O(n))
# ---------------------------------------------------------------------------

def _find_local_extrema(arr: np.ndarray, order: int = 5) -> tuple[list[int], list[int]]:
    """로컬 최소/최대 인덱스 반환.

    order봉 좌우를 비교해 극값 판정.
    look-ahead 방지: 호출자가 `k + order < current_bar` 필터를 적용해야 함.
    """
    mins: list[int] = []
    maxs: list[int] = []
    for k in range(order, len(arr) - order):
        if all(arr[k] <= arr[k - j] for j in range(1, order + 1)) and \
           all(arr[k] <= arr[k + j] for j in range(1, order + 1)):
            mins.append(k)
        if all(arr[k] >= arr[k - j] for j in range(1, order + 1)) and \
           all(arr[k] >= arr[k + j] for j in range(1, order + 1)):
            maxs.append(k)
    return mins, maxs


def _confirmed_before(indices: list[int], current_i: int, lookback: int, order: int) -> list[int]:
    """현재 봉 기준으로 확정된 극값만 필터. k + order <= current_i - 1."""
    return [m for m in indices if current_i - lookback <= m <= current_i - order - 1]


# ---------------------------------------------------------------------------
# 패턴 1: Double Bottom (LONG)
# ---------------------------------------------------------------------------

def run_double_bottom_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    tolerance: float = 0.02,
    lookback: int = 50,
    extrema_order: int = 5,
) -> StrategyResult:
    """Double Bottom 패턴 — 두 저점이 tolerance 이내 + 넥라인 돌파 시 LONG."""
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    low_mins, low_maxs = _find_local_extrema(low, order=extrema_order)
    high_mins, high_maxs = _find_local_extrema(high, order=extrema_order)
    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_low <= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_high >= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (exit_price - pos_entry) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="DOUBLE_BOTTOM", entry_date=pos_entry_date,
                    exit_date=bar_date, side="LONG", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position:
            recent_mins = _confirmed_before(low_mins, i, lookback, extrema_order)
            if len(recent_mins) < 2:
                continue

            m2 = recent_mins[-1]
            m1 = recent_mins[-2]
            low1, low2 = float(low[m1]), float(low[m2])

            if abs(low1 - low2) / max(low1, low2) > tolerance:
                continue

            # 넥라인: 두 저점 사이 high의 최고점 (확정된 극값)
            between_maxs = [m for m in high_maxs if m1 < m < m2 and m <= i - extrema_order - 1]
            if not between_maxs:
                # 극값이 없으면 단순 구간 최고점 사용
                neckline = float(np.max(high[m1:m2 + 1]))
            else:
                neckline = max(float(high[m]) for m in between_maxs)

            if bar_close <= neckline:
                continue

            pos_entry = bar_close
            pos_sl = min(low1, low2) * 0.998
            sl_dist = pos_entry - pos_sl
            pos_tp = pos_entry + tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (last_close - pos_entry) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="DOUBLE_BOTTOM", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="LONG", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("DOUBLE_BOTTOM", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 패턴 2: Double Top (SHORT)
# ---------------------------------------------------------------------------

def run_double_top_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    tolerance: float = 0.02,
    lookback: int = 50,
    extrema_order: int = 5,
) -> StrategyResult:
    """Double Top 패턴 — 두 고점 유사 + 넥라인 하향 이탈 시 SHORT."""
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    low_mins, low_maxs = _find_local_extrema(low, order=extrema_order)
    high_mins, high_maxs = _find_local_extrema(high, order=extrema_order)
    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_high >= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_low <= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="DOUBLE_TOP", entry_date=pos_entry_date,
                    exit_date=bar_date, side="SHORT", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position:
            recent_maxs = _confirmed_before(high_maxs, i, lookback, extrema_order)
            if len(recent_maxs) < 2:
                continue

            m2 = recent_maxs[-1]
            m1 = recent_maxs[-2]
            high1, high2 = float(high[m1]), float(high[m2])

            if abs(high1 - high2) / max(high1, high2) > tolerance:
                continue

            # 넥라인: 두 고점 사이 low의 최저점
            between_mins = [m for m in low_mins if m1 < m < m2 and m <= i - extrema_order - 1]
            if not between_mins:
                neckline = float(np.min(low[m1:m2 + 1]))
            else:
                neckline = min(float(low[m]) for m in between_mins)

            if bar_close >= neckline:
                continue

            pos_entry = bar_close
            pos_sl = max(high1, high2) * 1.002
            sl_dist = pos_sl - pos_entry
            pos_tp = pos_entry - tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (pos_entry - last_close) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="DOUBLE_TOP", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="SHORT", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("DOUBLE_TOP", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 패턴 3: Bull Flag (LONG)
# ---------------------------------------------------------------------------

def run_bull_flag_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    pole_bars: int = 10,
    pole_min_pct: float = 3.0,
    flag_bars: int = 15,
    flag_max_retrace: float = 0.5,
) -> StrategyResult:
    """Bull Flag — 급등(pole) 후 하향 조정(flag) + 상방 돌파.

    미래 참조 없음: pole/flag 구간은 현재 봉 이전의 고정 윈도우.
    """
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_low <= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_high >= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (exit_price - pos_entry) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="BULL_FLAG", entry_date=pos_entry_date,
                    exit_date=bar_date, side="LONG", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position and i >= start_idx + pole_bars + flag_bars:
            # Pole: pole_bars 동안의 상승률 (현재 봉 이전 고정 윈도우)
            pole_start = i - pole_bars - flag_bars
            pole_end = i - flag_bars
            pole_low = float(np.min(low[pole_start:pole_end + 1]))
            pole_high = float(np.max(high[pole_start:pole_end + 1]))
            pole_pct = (pole_high - pole_low) / pole_low * 100

            if pole_pct < pole_min_pct:
                continue

            # Flag: flag_bars 동안의 조정
            flag_slice_high = high[pole_end:i]
            flag_slice_low = low[pole_end:i]
            flag_high = float(np.max(flag_slice_high))
            flag_low = float(np.min(flag_slice_low))
            pole_range = pole_high - pole_low

            retrace = (pole_high - flag_low) / pole_range if pole_range > 0 else 1.0
            if retrace > flag_max_retrace:
                continue

            flag_range = flag_high - flag_low
            if flag_range >= pole_range * 0.5:
                continue

            if bar_close <= flag_high:
                continue

            pos_entry = bar_close
            pos_sl = flag_low * 0.998
            sl_dist = pos_entry - pos_sl
            pos_tp = pos_entry + tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (last_close - pos_entry) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="BULL_FLAG", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="LONG", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("BULL_FLAG", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 패턴 4: Bear Flag (SHORT)
# ---------------------------------------------------------------------------

def run_bear_flag_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    pole_bars: int = 10,
    pole_min_pct: float = 3.0,
    flag_bars: int = 15,
    flag_max_retrace: float = 0.5,
) -> StrategyResult:
    """Bear Flag — 급락(pole) 후 상향 조정(flag) + 하방 돌파."""
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_high >= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_low <= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="BEAR_FLAG", entry_date=pos_entry_date,
                    exit_date=bar_date, side="SHORT", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position and i >= start_idx + pole_bars + flag_bars:
            pole_start = i - pole_bars - flag_bars
            pole_end = i - flag_bars
            pole_high = float(np.max(high[pole_start:pole_end + 1]))
            pole_low = float(np.min(low[pole_start:pole_end + 1]))
            pole_pct = (pole_high - pole_low) / pole_high * 100

            if pole_pct < pole_min_pct:
                continue

            pole_start_close = float(close[pole_start])
            pole_end_close = float(close[pole_end])
            if pole_end_close >= pole_start_close:
                continue

            flag_slice_high = high[pole_end:i]
            flag_slice_low = low[pole_end:i]
            flag_high = float(np.max(flag_slice_high))
            flag_low = float(np.min(flag_slice_low))
            pole_range = pole_high - pole_low

            retrace = (flag_high - pole_low) / pole_range if pole_range > 0 else 1.0
            if retrace > flag_max_retrace:
                continue

            flag_range = flag_high - flag_low
            if flag_range >= pole_range * 0.5:
                continue

            if bar_close >= flag_low:
                continue

            pos_entry = bar_close
            pos_sl = flag_high * 1.002
            sl_dist = pos_sl - pos_entry
            pos_tp = pos_entry - tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (pos_entry - last_close) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="BEAR_FLAG", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="SHORT", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("BEAR_FLAG", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 패턴 5: Ascending Triangle (LONG)
# ---------------------------------------------------------------------------

def run_asc_triangle_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    lookback: int = 40,
    extrema_order: int = 5,
    resistance_tol: float = 0.01,
) -> StrategyResult:
    """Ascending Triangle — 수평 저항 + 상승 지지선 + 상방 돌파."""
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    low_mins, _ = _find_local_extrema(low, order=extrema_order)
    _, high_maxs = _find_local_extrema(high, order=extrema_order)
    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_low <= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_high >= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (exit_price - pos_entry) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="ASC_TRIANGLE", entry_date=pos_entry_date,
                    exit_date=bar_date, side="LONG", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position:
            # 수평 저항: 확정된 고점 2개 이상이 유사
            recent_maxs = _confirmed_before(high_maxs, i, lookback, extrema_order)
            if len(recent_maxs) < 2:
                continue

            highs_at_maxs = [float(high[m]) for m in recent_maxs[-3:]]
            resistance = np.mean(highs_at_maxs)
            if max(abs(h - resistance) / resistance for h in highs_at_maxs) > resistance_tol:
                continue

            # 상승 지지: 확정된 저점들이 상승 추세
            recent_mins = _confirmed_before(low_mins, i, lookback, extrema_order)
            if len(recent_mins) < 2:
                continue

            lows_at_mins = [float(low[m]) for m in recent_mins[-3:]]
            if not all(lows_at_mins[j] < lows_at_mins[j + 1] for j in range(len(lows_at_mins) - 1)):
                continue

            if bar_close <= resistance:
                continue

            pos_entry = bar_close
            pos_sl = lows_at_mins[-1] * 0.998
            sl_dist = pos_entry - pos_sl
            pos_tp = pos_entry + tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (last_close - pos_entry) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="ASC_TRIANGLE", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="LONG", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("ASC_TRIANGLE", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 패턴 6: Descending Triangle (SHORT)
# ---------------------------------------------------------------------------

def run_desc_triangle_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    tp_ratio: float = 2.0,
    lookback: int = 40,
    extrema_order: int = 5,
    support_tol: float = 0.01,
) -> StrategyResult:
    """Descending Triangle — 수평 지지 + 하강 저항선 + 하방 돌파."""
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    low_mins, _ = _find_local_extrema(low, order=extrema_order)
    _, high_maxs = _find_local_extrema(high, order=extrema_order)
    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if bar_high >= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif bar_low <= pos_tp:
                exit_reason, exit_price = "TP", pos_tp
            elif pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="DESC_TRIANGLE", entry_date=pos_entry_date,
                    exit_date=bar_date, side="SHORT", entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position:
            # 수평 지지: 확정된 저점들이 유사
            recent_mins = _confirmed_before(low_mins, i, lookback, extrema_order)
            if len(recent_mins) < 2:
                continue

            lows_at_mins = [float(low[m]) for m in recent_mins[-3:]]
            support = np.mean(lows_at_mins)
            if max(abs(lv - support) / support for lv in lows_at_mins) > support_tol:
                continue

            # 하강 저항: 확정된 고점들이 하락 추세
            recent_maxs = _confirmed_before(high_maxs, i, lookback, extrema_order)
            if len(recent_maxs) < 2:
                continue

            highs_at_maxs = [float(high[m]) for m in recent_maxs[-3:]]
            if not all(highs_at_maxs[j] > highs_at_maxs[j + 1] for j in range(len(highs_at_maxs) - 1)):
                continue

            if bar_close >= support:
                continue

            pos_entry = bar_close
            pos_sl = highs_at_maxs[-1] * 1.002
            sl_dist = pos_sl - pos_entry
            pos_tp = pos_entry - tp_ratio * sl_dist
            pos_entry_date = bar_date
            pos_bars = 0
            bar_ts = df.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
            in_position = True

    if in_position:
        last_close = float(close[-1])
        pnl_pct = (pos_entry - last_close) / pos_entry - fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy="DESC_TRIANGLE", entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19], side="SHORT", entry_price=pos_entry,
            exit_price=last_close, exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
        ))

    return _build_result("DESC_TRIANGLE", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def _build_result(name: str, symbol: str, timeframe: str,
                  start: str, end: str, trades: list[StrategyTrade]) -> StrategyResult:
    result = calc_metrics(trades)
    if result is None:
        return StrategyResult(
            strategy=name, symbol=symbol, timeframe=timeframe,
            start_date=start, end_date=end, total_trades=0, wins=0, losses=0,
            win_rate=0.0, avg_win_pct=0.0, avg_loss_pct=0.0, profit_factor=0.0,
            trades=[],
        )
    result.symbol = symbol
    result.timeframe = timeframe
    result.start_date = start
    result.end_date = end
    return result

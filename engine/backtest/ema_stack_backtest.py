"""Triple EMA Stack 추세추종 전략 백테스트 엔진.

진입 조건:
  LONG:  EMA8 > EMA21 > EMA55 (정배열) AND ADX(14) > 25 AND close <= EMA21*(1+0.002)
  SHORT: EMA8 < EMA21 < EMA55 (역배열) AND ADX(14) > 25 AND close >= EMA21*(1-0.002)
SL: LONG → EMA55 * 0.998, SHORT → EMA55 * 1.002
TP: entry ± tp_ratio × |entry - sl|
시간제한: 30봉
타임프레임: 1H
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

STRATEGY_NAME = "EMA_STACK"


def run_ema_stack_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    adx_threshold: float = 25.0,
    tp_ratio: float = 2.4,
    pullback_tolerance: float = 0.002,
) -> StrategyResult:
    """Triple EMA Stack 전략 백테스트 실행."""
    # --- 데이터 로드 ---
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    # --- 지표 계산 ---
    ema8 = talib.EMA(close, timeperiod=8)
    ema21 = talib.EMA(close, timeperiod=21)
    ema55 = talib.EMA(close, timeperiod=55)
    adx = talib.ADX(high, low, close, timeperiod=14)

    start_idx = get_start_idx(df, start)

    # --- 백테스트 루프 ---
    trades: list[StrategyTrade] = []
    in_position = False
    pos_side = ""
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_entry_date = ""
    pos_bars = 0
    pos_regime = "RANGE"

    for i in range(start_idx, len(df)):
        if (np.isnan(ema8[i]) or np.isnan(ema21[i])
                or np.isnan(ema55[i]) or np.isnan(adx[i])):
            continue

        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        e8 = float(ema8[i])
        e21 = float(ema21[i])
        e55 = float(ema55[i])
        adx_val = float(adx[i])

        # --- 포지션 관리 ---
        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            # SL 체크 (high/low 기준)
            if pos_side == "LONG" and bar_low <= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl
            elif pos_side == "SHORT" and bar_high >= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl

            # TP 체크 (high/low 기준)
            if exit_reason is None:
                if pos_side == "LONG" and bar_high >= pos_tp:
                    exit_reason = "TP"
                    exit_price = pos_tp
                elif pos_side == "SHORT" and bar_low <= pos_tp:
                    exit_reason = "TP"
                    exit_price = pos_tp

            # 시간제한
            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason = "TIME"
                exit_price = bar_close

            if exit_reason is not None:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry

                pnl_pct -= fee_rate * 2  # 수수료 차감 먼저
                pnl_pct *= leverage       # 그 다음 레버리지

                trades.append(StrategyTrade(
                    strategy=STRATEGY_NAME,
                    entry_date=pos_entry_date,
                    exit_date=bar_date,
                    side=pos_side,
                    entry_price=pos_entry,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2),
                    market_regime=pos_regime,
                ))
                in_position = False

        # --- 신규 진입 ---
        if not in_position:
            if adx_val <= adx_threshold:
                continue  # 추세가 약하면 스킵

            long_aligned = e8 > e21 > e55
            short_aligned = e8 < e21 < e55

            if long_aligned and bar_close <= e21 * (1 + pullback_tolerance):
                # LONG: 정배열 + EMA21 풀백
                pos_side = "LONG"
                pos_entry = bar_close
                pos_sl = e55 * (1 - pullback_tolerance)
                sl_dist = abs(pos_entry - pos_sl)
                pos_tp = pos_entry + tp_ratio * sl_dist
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

            elif short_aligned and bar_close >= e21 * (1 - pullback_tolerance):
                # SHORT: 역배열 + EMA21 풀백
                pos_side = "SHORT"
                pos_entry = bar_close
                pos_sl = e55 * (1 + pullback_tolerance)
                sl_dist = abs(pos_sl - pos_entry)
                pos_tp = pos_entry - tp_ratio * sl_dist
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

    # --- 미청산 포지션 ---
    if in_position:
        last_close = float(close[-1])
        if pos_side == "LONG":
            pnl_pct = (last_close - pos_entry) / pos_entry
        else:
            pnl_pct = (pos_entry - last_close) / pos_entry
        pnl_pct -= fee_rate * 2
        pnl_pct *= leverage
        trades.append(StrategyTrade(
            strategy=STRATEGY_NAME,
            entry_date=pos_entry_date,
            exit_date=str(df.index[-1])[:19],
            side=pos_side,
            entry_price=pos_entry,
            exit_price=last_close,
            exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2),
            market_regime=pos_regime,
        ))

    # --- 메트릭 ---
    result = calc_metrics(trades)
    if result is None:
        return StrategyResult(
            strategy=STRATEGY_NAME, symbol=symbol, timeframe=timeframe,
            start_date=start, end_date=end, total_trades=0, wins=0, losses=0,
            win_rate=0.0, avg_win_pct=0.0, avg_loss_pct=0.0, profit_factor=0.0,
            trades=[],
        )

    result.symbol = symbol
    result.timeframe = timeframe
    result.start_date = start
    result.end_date = end
    return result

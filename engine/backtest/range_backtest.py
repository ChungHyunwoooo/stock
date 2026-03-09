"""횡보장 전용 전략 백테스트.

전략 목록:
  1. Range Scalper — ATR 수축 감지 + 레인지 경계 반등
  2. Pairs Mean Reversion — BTC/ETH 스프레드 회귀
  3. Stoch RSI Reversal — 과매수/과매도 반전 (레인지 확인 후)

공통:
  횡보 판별: ADX < 20 AND BB Width < 중앙값
  타임프레임: 1H
  시간제한: 15봉 (횡보는 짧게 청산)
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
# 전략 1: Range Scalper
# ---------------------------------------------------------------------------

def run_range_scalper_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 15,
    adx_threshold: float = 20.0,
    range_lookback: int = 30,
    tp_ratio: float = 1.5,
    edge_pct: float = 0.15,
) -> StrategyResult:
    """Range Scalper — 레인지 상/하단 반등.

    1. ADX < 20 으로 횡보 확인
    2. 최근 range_lookback봉의 고/저를 레인지로 설정
    3. 가격이 레인지 하단 edge_pct 이내 → LONG, 상단 edge_pct 이내 → SHORT
    4. TP: 레인지 중앙 방향, SL: 레인지 이탈
    """
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    adx = talib.ADX(high, low, close, timeperiod=14)
    atr = talib.ATR(high, low, close, timeperiod=14)
    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_side = ""
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        if np.isnan(adx[i]) or np.isnan(atr[i]):
            continue

        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if pos_side == "LONG":
                if bar_low <= pos_sl:
                    exit_reason, exit_price = "SL", pos_sl
                elif bar_high >= pos_tp:
                    exit_reason, exit_price = "TP", pos_tp
            else:
                if bar_high >= pos_sl:
                    exit_reason, exit_price = "SL", pos_sl
                elif bar_low <= pos_tp:
                    exit_reason, exit_price = "TP", pos_tp

            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="RANGE_SCALPER", entry_date=pos_entry_date,
                    exit_date=bar_date, side=pos_side, entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position and i >= range_lookback:
            adx_val = float(adx[i])
            if adx_val >= adx_threshold:
                continue

            # 레인지 계산
            range_high = float(np.max(high[i - range_lookback:i]))
            range_low = float(np.min(low[i - range_lookback:i]))
            range_size = range_high - range_low
            if range_size <= 0:
                continue

            range_mid = (range_high + range_low) / 2
            edge_dist = range_size * edge_pct

            atr_val = float(atr[i])

            if bar_close <= range_low + edge_dist:
                # 하단 반등 → LONG
                pos_side = "LONG"
                pos_entry = bar_close
                pos_sl = range_low - atr_val * 0.5
                tp_target = range_mid
                pos_tp = pos_entry + min(tp_target - pos_entry, tp_ratio * (pos_entry - pos_sl))
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

            elif bar_close >= range_high - edge_dist:
                # 상단 반등 → SHORT
                pos_side = "SHORT"
                pos_entry = bar_close
                pos_sl = range_high + atr_val * 0.5
                tp_target = range_mid
                pos_tp = pos_entry - min(pos_entry - tp_target, tp_ratio * (pos_sl - pos_entry))
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

    if in_position:
        _close_position(trades, "RANGE_SCALPER", pos_side, pos_entry,
                        float(close[-1]), str(df.index[-1])[:19],
                        pos_entry_date, pos_regime, fee_rate, leverage)

    return _build_result("RANGE_SCALPER", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 전략 2: Pairs Mean Reversion (BTC vs ETH 스프레드)
# ---------------------------------------------------------------------------

def run_pairs_mr_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 15,
    zscore_entry: float = 2.0,
    zscore_exit: float = 0.5,
    lookback: int = 72,
) -> StrategyResult:
    """Pairs MR — BTC/ETH 비율의 z-score 기반 평균회귀.

    단일 심볼 백테스트이므로, BTC/ETH 비율 대신
    close / SMA(close, lookback)의 z-score 사용.
    """
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    adx = talib.ADX(high, low, close, timeperiod=14)
    sma = talib.SMA(close, timeperiod=lookback)
    stddev = talib.STDDEV(close, timeperiod=lookback)
    atr = talib.ATR(high, low, close, timeperiod=14)

    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_side = ""
    pos_entry = pos_sl = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        if np.isnan(sma[i]) or np.isnan(stddev[i]) or stddev[i] <= 0 or np.isnan(adx[i]):
            continue

        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        zscore = (bar_close - float(sma[i])) / float(stddev[i])

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            # SL 체크
            if pos_side == "LONG" and bar_low <= pos_sl:
                exit_reason, exit_price = "SL", pos_sl
            elif pos_side == "SHORT" and bar_high >= pos_sl:
                exit_reason, exit_price = "SL", pos_sl

            # Z-score 회귀 → TP
            if exit_reason is None:
                if pos_side == "LONG" and zscore >= zscore_exit:
                    exit_reason, exit_price = "TP", bar_close
                elif pos_side == "SHORT" and zscore <= -zscore_exit:
                    exit_reason, exit_price = "TP", bar_close

            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="PAIRS_MR", entry_date=pos_entry_date,
                    exit_date=bar_date, side=pos_side, entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position:
            adx_val = float(adx[i])
            if adx_val >= 20:
                continue  # 횡보장만

            atr_val = float(atr[i])

            if zscore <= -zscore_entry:
                pos_side = "LONG"
                pos_entry = bar_close
                pos_sl = bar_close - atr_val * 2.0
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

            elif zscore >= zscore_entry:
                pos_side = "SHORT"
                pos_entry = bar_close
                pos_sl = bar_close + atr_val * 2.0
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

    if in_position:
        _close_position(trades, "PAIRS_MR", pos_side, pos_entry,
                        float(close[-1]), str(df.index[-1])[:19],
                        pos_entry_date, pos_regime, fee_rate, leverage)

    return _build_result("PAIRS_MR", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 전략 3: Stoch RSI Reversal
# ---------------------------------------------------------------------------

def run_stoch_rsi_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 15,
    adx_threshold: float = 20.0,
    stoch_oversold: float = 15.0,
    stoch_overbought: float = 85.0,
    rsi_filter_low: float = 35.0,
    rsi_filter_high: float = 65.0,
    tp_atr_mult: float = 1.5,
    sl_atr_mult: float = 1.0,
) -> StrategyResult:
    """Stoch RSI Reversal — 횡보장에서 Stochastic 극단값 반전.

    1. ADX < 20 (횡보 확인)
    2. RSI가 35~65 사이 (추세 아님 확인)
    3. Stoch %K < 15 + %K가 %D 상향교차 → LONG
    4. Stoch %K > 85 + %K가 %D 하향교차 → SHORT
    """
    df = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    adx = talib.ADX(high, low, close, timeperiod=14)
    rsi = talib.RSI(close, timeperiod=14)
    slowk, slowd = talib.STOCH(high, low, close,
                                fastk_period=14, slowk_period=3, slowd_period=3)
    atr = talib.ATR(high, low, close, timeperiod=14)

    start_idx = get_start_idx(df, start)

    trades: list[StrategyTrade] = []
    in_position = False
    pos_side = ""
    pos_entry = pos_sl = pos_tp = pos_bars = 0.0
    pos_entry_date = pos_regime = ""

    for i in range(start_idx, len(df)):
        if any(np.isnan(v[i]) for v in [adx, rsi, slowk, slowd, atr]):
            continue

        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        bar_date = str(df.index[i])[:19]

        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            if pos_side == "LONG":
                if bar_low <= pos_sl:
                    exit_reason, exit_price = "SL", pos_sl
                elif bar_high >= pos_tp:
                    exit_reason, exit_price = "TP", pos_tp
            else:
                if bar_high >= pos_sl:
                    exit_reason, exit_price = "SL", pos_sl
                elif bar_low <= pos_tp:
                    exit_reason, exit_price = "TP", pos_tp

            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason, exit_price = "TIME", bar_close

            if exit_reason:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                trades.append(StrategyTrade(
                    strategy="STOCH_RSI", entry_date=pos_entry_date,
                    exit_date=bar_date, side=pos_side, entry_price=pos_entry,
                    exit_price=exit_price, exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2), market_regime=pos_regime,
                ))
                in_position = False

        if not in_position and i >= 1:
            adx_val = float(adx[i])
            rsi_val = float(rsi[i])
            k_val = float(slowk[i])
            d_val = float(slowd[i])
            k_prev = float(slowk[i - 1])
            d_prev = float(slowd[i - 1])
            atr_val = float(atr[i])

            if adx_val >= adx_threshold:
                continue
            if rsi_val < rsi_filter_low or rsi_val > rsi_filter_high:
                continue

            # LONG: %K < oversold + 골든크로스
            if k_val < stoch_oversold and k_prev <= d_prev and k_val > d_val:
                pos_side = "LONG"
                pos_entry = bar_close
                pos_sl = bar_close - sl_atr_mult * atr_val
                pos_tp = bar_close + tp_atr_mult * atr_val
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

            # SHORT: %K > overbought + 데드크로스
            elif k_val > stoch_overbought and k_prev >= d_prev and k_val < d_val:
                pos_side = "SHORT"
                pos_entry = bar_close
                pos_sl = bar_close + sl_atr_mult * atr_val
                pos_tp = bar_close - tp_atr_mult * atr_val
                pos_entry_date = bar_date
                pos_bars = 0
                bar_ts = df.index[i]
                d1_slice = df_1d[df_1d.index <= bar_ts]
                pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"
                in_position = True

    if in_position:
        _close_position(trades, "STOCH_RSI", pos_side, pos_entry,
                        float(close[-1]), str(df.index[-1])[:19],
                        pos_entry_date, pos_regime, fee_rate, leverage)

    return _build_result("STOCH_RSI", symbol, timeframe, start, end, trades)


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def _close_position(trades, strategy, side, entry, last_close, exit_date,
                    entry_date, regime, fee_rate, leverage):
    if side == "LONG":
        pnl_pct = (last_close - entry) / entry
    else:
        pnl_pct = (entry - last_close) / entry
    pnl_pct -= fee_rate * 2
    pnl_pct *= leverage
    trades.append(StrategyTrade(
        strategy=strategy, entry_date=entry_date, exit_date=exit_date,
        side=side, entry_price=entry, exit_price=last_close,
        exit_reason="END", pnl_pct=round(pnl_pct * 100, 2),
        market_regime=regime,
    ))


def _build_result(name, symbol, timeframe, start, end, trades):
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

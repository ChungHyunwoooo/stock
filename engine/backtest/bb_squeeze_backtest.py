"""BB Squeeze→Expansion 전략 백테스트 엔진.

진입 조건:
  - BB(20,2)가 Keltner Channel(20, 1.5×ATR) 안에 완전히 들어가면 "squeeze" 상태
  - Squeeze 해제(expansion) + MACD 히스토그램 방향으로 진입
    - histogram > 0 → LONG
    - histogram < 0 → SHORT
SL: 1.5 × ATR(14)
TP: 2.5 × SL 거리 (R:R = 2.5)
시간제한: 30봉
타임프레임: 1H
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import talib

from engine.backtest.strategy_base import (
    StrategyResult,
    StrategyTrade,
    calc_metrics,
    detect_regime,
    get_start_idx,
    load_ohlcv,
)

logger = logging.getLogger(__name__)

STRATEGY_NAME = "BB_SQUEEZE"


def run_bb_squeeze_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    timeframe: str = "1h",
    leverage: int = 3,
    fee_rate: float = 0.0004,
    max_hold_bars: int = 30,
    atr_sl_mult: float = 1.5,
    tp_ratio: float = 2.5,
) -> StrategyResult:
    """BB Squeeze→Expansion 전략 백테스트 실행.

    Args:
        symbol: 심볼 (e.g. "BTC/USDT")
        start: 백테스트 시작일 "YYYY-MM-DD"
        end: 백테스트 종료일 "YYYY-MM-DD"
        timeframe: 타임프레임 (기본 "1h")
        leverage: 레버리지 배수
        fee_rate: 편도 수수료율 (진입+청산 × 2 적용)
        max_hold_bars: 최대 보유 봉 수
        atr_sl_mult: SL = atr_sl_mult × ATR(14)
        tp_ratio: TP = tp_ratio × SL 거리

    Returns:
        StrategyResult 인스턴스
    """
    # --- 데이터 로드 ---
    df_1h = load_ohlcv(symbol, start, end, timeframe, lookback_bars=300)
    df_1d = load_ohlcv(symbol, start, end, "1d", lookback_bars=300)

    # --- 지표 계산 (전체 배열) ---
    close = df_1h["close"].values.astype(np.float64)
    high = df_1h["high"].values.astype(np.float64)
    low = df_1h["low"].values.astype(np.float64)

    # Bollinger Bands (20, 2)
    bb_upper, bb_middle, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)

    # ATR(14) — Keltner 중심선 + SL 계산에 공용
    atr = talib.ATR(high, low, close, timeperiod=14)

    # Keltner Channel: middle ± 1.5 × ATR (middle = BB middle = EMA20)
    kc_upper = bb_middle + 1.5 * atr
    kc_lower = bb_middle - 1.5 * atr

    # MACD (12, 26, 9)
    _macd, _signal, histogram = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)

    # Squeeze 감지: BB upper < KC upper AND BB lower > KC lower
    # (BB 밴드가 KC 안에 완전히 포함된 상태)
    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # --- 백테스트 루프 ---
    start_idx = get_start_idx(df_1h, start)

    trades: list[StrategyTrade] = []

    in_position = False
    pos_side = ""
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_entry_date = ""
    pos_bars = 0
    pos_regime = "RANGE"

    for i in range(start_idx, len(df_1h)):
        bar = df_1h.iloc[i]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        bar_close = float(bar["close"])
        bar_date = str(df_1h.index[i])[:19]

        # --- 포지션 관리 ---
        if in_position:
            pos_bars += 1
            exit_reason: str | None = None
            exit_price = bar_close

            # SL 체크
            if pos_side == "LONG" and bar_low <= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl
            elif pos_side == "SHORT" and bar_high >= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl

            # TP 체크
            if exit_reason is None:
                if pos_side == "LONG" and bar_high >= pos_tp:
                    exit_reason = "TP"
                    exit_price = pos_tp
                elif pos_side == "SHORT" and bar_low <= pos_tp:
                    exit_reason = "TP"
                    exit_price = pos_tp

            # 시간 제한
            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason = "TIME"
                exit_price = bar_close

            if exit_reason is not None:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry

                pnl_pct -= fee_rate * 2  # 수수료 차감 (진입+청산)
                pnl_pct *= leverage      # 레버리지 적용

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

        # --- 신규 진입 판단 ---
        if not in_position and i >= start_idx + 1:
            prev_i = i - 1

            # 지표 유효성 검사
            if (np.isnan(squeeze[prev_i]) or np.isnan(squeeze[i])
                    or np.isnan(histogram[i])
                    or np.isnan(atr[i])):
                continue

            # 진입 조건: 이전봉 squeeze AND 현재봉 not squeeze (expansion)
            prev_squeeze = bool(squeeze[prev_i])
            curr_squeeze = bool(squeeze[i])

            if not prev_squeeze or curr_squeeze:
                # expansion이 아니거나, 이전봉이 squeeze 아님 → 스킵
                continue

            hist_val = float(histogram[i])
            if hist_val == 0.0:
                continue

            side_str = "LONG" if hist_val > 0 else "SHORT"

            # SL / TP 계산
            atr_val = float(atr[i])
            if atr_val <= 0 or np.isnan(atr_val):
                atr_val = bar_close * 0.02  # 폴백

            sl_dist = atr_val * atr_sl_mult
            tp_dist = sl_dist * tp_ratio

            direction = 1 if side_str == "LONG" else -1
            pos_entry = bar_close
            pos_sl = bar_close - direction * sl_dist
            pos_tp = bar_close + direction * tp_dist
            pos_side = side_str
            pos_entry_date = bar_date
            pos_bars = 0

            # 레짐: D1 데이터에서 진입 시점 기준 슬라이스 후 detect_regime 호출
            bar_ts = df_1h.index[i]
            d1_slice = df_1d[df_1d.index <= bar_ts]
            pos_regime = detect_regime(d1_slice) if len(d1_slice) >= 200 else "RANGE"

            in_position = True

    # --- 미청산 포지션 END 처리 ---
    if in_position:
        last_close = float(df_1h["close"].iloc[-1])
        if pos_side == "LONG":
            pnl_pct = (last_close - pos_entry) / pos_entry
        else:
            pnl_pct = (pos_entry - last_close) / pos_entry
        pnl_pct -= fee_rate * 2
        pnl_pct *= leverage

        trades.append(StrategyTrade(
            strategy=STRATEGY_NAME,
            entry_date=pos_entry_date,
            exit_date=str(df_1h.index[-1])[:19],
            side=pos_side,
            entry_price=pos_entry,
            exit_price=last_close,
            exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2),
            market_regime=pos_regime,
        ))

    # --- 메트릭 집계 ---
    result = calc_metrics(trades)
    if result is None:
        # 트레이드 없음 → 빈 결과 반환
        return StrategyResult(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start,
            end_date=end,
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            profit_factor=0.0,
            trades=[],
        )

    # calc_metrics가 반환한 결과에 symbol/timeframe 덮어쓰기
    result.symbol = symbol
    result.timeframe = timeframe
    result.start_date = start
    result.end_date = end

    return result

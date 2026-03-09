"""Mega Pump Precursor Detector — 급등 전조 패턴 감지.

업비트 KRW 시장에서 대형 급등 직전에 나타나는 복합 신호를 점수화.
지표 단독이 아니라 가격 구조 + 거래량 행동 + 지표 교차검증으로 판단.

기존 upbit_scanner.py의 scan_* 인터페이스를 따름:
  (df, symbol, config, context) -> Signal | None
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib

from engine.alerts.discord import Signal


def scan_mega_pump_precursor(
    df: pd.DataFrame,
    symbol: str,
    config=None,
    context: dict | None = None,
) -> Signal | None:
    """급등 전조 패턴 감지 (LONG only).

    7가지 조건을 점수화하여 3.0점 이상일 때 시그널 발생.
    TP는 과거 가격 구조(이전 고점, 피보나치 확장)에서 도출.
    """
    from engine.strategy.upbit_scanner import (
        UpbitScannerConfig,
        _tick_round,
        calc_confidence_v2,
        calc_dynamic_levels,
    )

    cfg = config or UpbitScannerConfig()
    if len(df) < 60:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values

    curr_close = float(close[-1])
    ctx = context or {}
    kl = ctx.get("key_levels", {})
    structure = ctx.get("structure", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    adx_ctx = ctx.get("adx", {})

    score = 0.0
    reasons = []

    # --- 1) BB Squeeze: 밴드 폭의 퍼센타일 (데이터 기반) ---
    bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    if not np.isnan(bb_upper[-1]) and not np.isnan(bb_lower[-1]) and bb_mid[-1] > 0:
        bandwidth = (bb_upper[-1] - bb_lower[-1]) / bb_mid[-1]
        bw_series = (bb_upper - bb_lower) / np.where(bb_mid > 0, bb_mid, 1)
        bw_lookback = bw_series[-40:]
        bw_valid = bw_lookback[~np.isnan(bw_lookback)]
        if len(bw_valid) > 10:
            bw_pctile = float(np.sum(bw_valid < bandwidth) / len(bw_valid))
            if bw_pctile < 0.15:
                score += 1.5
                reasons.append(f"BB스퀴즈(하위{bw_pctile:.0%})")
            elif bw_pctile < 0.25:
                score += 1.0
                reasons.append(f"BB압축(하위{bw_pctile:.0%})")

    # --- 2) 거래량 단계적 축적 (단기MA vs 장기MA 비율) ---
    vol_ma_10 = float(pd.Series(vol).rolling(10).mean().iloc[-1])
    vol_ma_30 = float(pd.Series(vol).rolling(30).mean().iloc[-1])
    if vol_ma_30 > 0:
        vol_accel = vol_ma_10 / vol_ma_30
        if vol_accel > 2.0:
            score += 1.5
            reasons.append(f"거래량축적{vol_accel:.1f}x")
        elif vol_accel > 1.5:
            score += 1.0
            reasons.append(f"거래량증가{vol_accel:.1f}x")

    # --- 3) OBV 상승 다이버전스 (가격 횡보 + OBV 상승 = 매집) ---
    obv = _calc_obv(close, vol)
    lookback = 20
    if len(obv) >= lookback:
        price_change_pct = (close[-1] - close[-lookback]) / close[-lookback] * 100
        obv_start = obv[-lookback]
        obv_end = obv[-1]
        obv_range = np.max(np.abs(obv[-lookback:]))
        if obv_range > 0:
            obv_change_norm = (obv_end - obv_start) / obv_range
        else:
            obv_change_norm = 0.0

        if -2 < price_change_pct < 5 and obv_change_norm > 0.3:
            score += 1.5
            reasons.append(f"OBV다이버전스(가격{price_change_pct:+.1f}%,OBV↑)")
        elif -2 < price_change_pct < 5 and obv_change_norm > 0.15:
            score += 0.8
            reasons.append(f"OBV상승(가격{price_change_pct:+.1f}%)")

    # --- 4) Higher Lows (가격 구조 — 지표 아님) ---
    if len(low) >= 30:
        seg1_low = float(np.min(low[-30:-20]))
        seg2_low = float(np.min(low[-20:-10]))
        seg3_low = float(np.min(low[-10:]))
        if seg1_low < seg2_low < seg3_low:
            hl_pct = (seg3_low - seg1_low) / seg1_low * 100
            score += 1.0
            reasons.append(f"저점높이기({hl_pct:+.1f}%)")

    # --- 5) 거래량 폭발 초기 (가격 대비 거래량 비대칭) ---
    vol_avg_20 = float(pd.Series(vol).rolling(20).mean().iloc[-4])
    if vol_avg_20 > 0:
        recent_max_vol = float(np.max(vol[-3:]))
        vol_spike = recent_max_vol / vol_avg_20
        price_3bar = (close[-1] - close[-4]) / close[-4] * 100 if close[-4] > 0 else 0
        if vol_spike >= 5.0 and 0 < price_3bar < 10:
            score += 2.0
            reasons.append(f"거래량폭발{vol_spike:.1f}x(가격+{price_3bar:.1f}%)")
        elif vol_spike >= 3.0 and 0 < price_3bar < 8:
            score += 1.0
            reasons.append(f"거래량급증{vol_spike:.1f}x(가격+{price_3bar:.1f}%)")

    # --- 6) ADX 방향 전환 (횡보 → 추세 시작) ---
    adx_val = float(adx_ctx.get("adx", 25))
    plus_di = float(adx_ctx.get("plus_di", 0))
    minus_di = float(adx_ctx.get("minus_di", 0))
    if adx_val < 25 and plus_di > minus_di and plus_di > 20:
        score += 1.0
        reasons.append(f"추세전환(ADX:{adx_val:.0f},+DI:{plus_di:.0f}>-DI:{minus_di:.0f})")

    # --- 7) 가격이 중요 이평선 위 (바닥 탈출 확인) ---
    ema_50 = talib.EMA(close, timeperiod=50)
    if not np.isnan(ema_50[-1]) and curr_close > ema_50[-1]:
        score += 0.5
        reasons.append("EMA50위")

    # --- 최소 점수 필터 ---
    if score < 3.0:
        return None

    if kl.get("at_resistance", False):
        return None

    # 신뢰도
    base_confidence = min(1.0, 0.3 + score * 0.1)
    confidence = calc_confidence_v2(base_confidence, adx_ctx, vol_ctx, structure, candle, kl, "LONG")

    # SL/TP
    sl, tps = calc_dynamic_levels(
        df, curr_close, "LONG",
        sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
        key_levels=kl, adx=adx_ctx,
    )

    # TP 데이터 기반 재산출
    if tps:
        tps = _calc_data_driven_tp(df, curr_close, _tick_round)

    return Signal(
        strategy="UPBIT_MEGA_PUMP",
        symbol=symbol, side="LONG", entry=curr_close,
        stop_loss=sl, take_profits=tps,
        leverage=cfg.leverage, timeframe="5m", confidence=confidence,
        reason=f"[급등전조 {score:.1f}pt] " + " | ".join(reasons),
    )


def _calc_obv(close: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """On-Balance Volume — 순수 가격/거래량 기반."""
    obv = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + vol[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - vol[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def _calc_data_driven_tp(
    df: pd.DataFrame, curr_close: float, tick_round
) -> list[float]:
    """TP를 과거 가격 구조에서 도출. 하드코딩 없음.

    TP1: ATR × 3 (단기 변동성)
    TP2: ATR × 6 (중기 변동성)
    TP3: max(120봉 최고가, 피보나치 1.618 확장, TP2 + ATR × 4)
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    atr = talib.ATR(high, low, close, timeperiod=14)
    curr_atr = float(atr[-1]) if not np.isnan(atr[-1]) else curr_close * 0.02

    tp1 = tick_round(curr_close + curr_atr * 3)
    tp2 = tick_round(curr_close + curr_atr * 6)

    # TP3: 과거 구조 기반
    lookback_bars = min(120, len(high))
    historical_high = float(np.max(high[-lookback_bars:]))

    swing_low = float(np.min(low[-lookback_bars:]))
    swing_range = curr_close - swing_low
    fib_ext = curr_close + swing_range * 0.618 if swing_range > 0 else curr_close + curr_atr * 10

    tp3_candidates = [historical_high, fib_ext, tp2 + curr_atr * 4]
    tp3_above = [t for t in tp3_candidates if t > curr_close]
    tp3 = tick_round(max(tp3_above)) if tp3_above else tick_round(curr_close + curr_atr * 10)

    return sorted([tp1, tp2, tp3])

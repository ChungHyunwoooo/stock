"""Tommy MACD 히스토그램 피크아웃 전략.

TommyTradingTV 강의 기반:
- MACD 골든/데드 크로스: 0선 기준 위치에 따라 신뢰도 차등
- 히스토그램 피크아웃: 교차보다 선행하는 모멘텀 전환 감지
- 0선에서 멀수록 의미 있는 교차

기존 upbit_scanner.py의 scan_* 인터페이스를 따름:
  (df, symbol, config, context) -> Signal | None
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib

from engine.alerts.discord import Signal


def scan_tommy_macd(
    df: pd.DataFrame,
    symbol: str,
    config=None,
    context: dict | None = None,
) -> Signal | None:
    """MACD 히스토그램 피크아웃 + 크로스 위치 전략.

    Tommy 강의 핵심 규칙:
    1. 히스토그램 피크아웃 = 모멘텀 전환의 선행 지표
    2. MACD/시그널 교차의 위치(0선 대비)가 신뢰도를 결정
    3. 0선 아래 골든크로스 = 강한 매수, 0선 위 데드크로스 = 강한 매도
    """
    from engine.strategy.upbit_scanner import (
        UpbitScannerConfig,
        calc_dynamic_levels,
    )
    from engine.analysis import calc_confidence_v2
    from engine.analysis.confidence import get_last_breakdown

    cfg = config or UpbitScannerConfig()
    if len(df) < cfg.macd_slow + 10:
        return None

    close = df["close"].values
    curr_close = float(close[-1])

    macd_line, signal_line, hist = talib.MACD(
        close,
        fastperiod=cfg.macd_fast,
        slowperiod=cfg.macd_slow,
        signalperiod=cfg.macd_signal,
    )

    if np.isnan(macd_line[-1]) or np.isnan(hist[-1]):
        return None

    ctx = context or {}
    kl = ctx.get("key_levels", {})
    candle = ctx.get("candle", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})

    curr_macd = float(macd_line[-1])
    curr_signal = float(signal_line[-1])
    curr_hist = float(hist[-1])

    # --- 히스토그램 피크아웃 감지 ---
    # 최근 5봉의 히스토그램 변화 추적
    hist_vals = [float(hist[i]) for i in range(-5, 0) if not np.isnan(hist[i])]
    if len(hist_vals) < 5:
        return None

    # 피크아웃: 절대값이 감소하기 시작 (3봉 연속)
    bullish_peakout = False  # 마이너스 히스토그램이 약해짐 = 매수 신호
    bearish_peakout = False  # 플러스 히스토그램이 약해짐 = 매도 신호

    # 마이너스 히스토그램 피크아웃 (Tommy: MACD < 0일 때 의미 있음)
    if (hist_vals[-3] < hist_vals[-2] < hist_vals[-1] < 0
            and curr_macd < 0):
        bullish_peakout = True

    # 플러스 히스토그램 피크아웃 (Tommy: MACD > 0일 때 의미 있음)
    if (hist_vals[-3] > hist_vals[-2] > hist_vals[-1] > 0
            and curr_macd > 0):
        bearish_peakout = True

    # --- MACD/시그널 교차 감지 ---
    prev_macd = float(macd_line[-2])
    prev_signal = float(signal_line[-2])

    golden_cross = prev_macd <= prev_signal and curr_macd > curr_signal
    dead_cross = prev_macd >= prev_signal and curr_macd < curr_signal

    # --- 0선 대비 거리 (신뢰도 계수) ---
    # ATR 대비 정규화하여 코인별 스케일 차이 제거
    atr = talib.ATR(df["high"].values, df["low"].values, close, timeperiod=14)
    curr_atr = float(atr[-1]) if not np.isnan(atr[-1]) else curr_close * 0.02
    zero_dist = abs(curr_macd) / curr_atr if curr_atr > 0 else 0

    # --- 점수화 ---
    score = 0.0
    reasons = []

    # LONG 신호
    if bullish_peakout or (golden_cross and curr_macd < 0):
        if kl.get("at_resistance", False):
            return None

        if bullish_peakout:
            score += 1.5
            reasons.append("히스토그램피크아웃↑")

        if golden_cross and curr_macd < 0:
            # 0선 아래 골든크로스 — 위치가 낮을수록 강함
            cross_score = min(2.0, 1.0 + zero_dist * 0.3)
            score += cross_score
            reasons.append(f"0선하골든크로스(거리:{zero_dist:.1f}ATR)")
        elif golden_cross:
            score += 0.5
            reasons.append("골든크로스(0선위)")

        # 보조 확인
        rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
        curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50
        if curr_rsi < 45:
            score += 0.5
            reasons.append(f"RSI과매도({curr_rsi:.0f})")

        if candle.get("bullish_engulfing") or candle.get("bullish_pin_bar"):
            score += 0.5
            reasons.append("반전캔들")

        vol_ratio = vol_ctx.get("ratio", 1.0)
        if vol_ratio > 1.5:
            score += 0.5
            reasons.append(f"거래량{vol_ratio:.1f}x")

        # 피크아웃 단독(1.5+0.5=2.0)은 부족 — 교차 or 2개 이상 보조 필요
        if score < 2.5:
            return None

        base_q = min(0.8, 0.4 + score * 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(
            df, curr_close, "LONG",
            sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
            key_levels=kl, adx=adx,
        )

        return Signal(
            strategy="UPBIT_TOMMY_MACD",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=f"[Tommy MACD {score:.1f}pt] " + " | ".join(reasons),
        )

    # SHORT 신호
    if bearish_peakout or (dead_cross and curr_macd > 0):
        if kl.get("at_support", False):
            return None

        if bearish_peakout:
            score += 1.5
            reasons.append("히스토그램피크아웃↓")

        if dead_cross and curr_macd > 0:
            cross_score = min(2.0, 1.0 + zero_dist * 0.3)
            score += cross_score
            reasons.append(f"0선상데드크로스(거리:{zero_dist:.1f}ATR)")
        elif dead_cross:
            score += 0.5
            reasons.append("데드크로스(0선하)")

        rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
        curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50
        if curr_rsi > 55:
            score += 0.5
            reasons.append(f"RSI과매수({curr_rsi:.0f})")

        if candle.get("bearish_engulfing") or candle.get("bearish_pin_bar"):
            score += 0.5
            reasons.append("반전캔들")

        vol_ratio = vol_ctx.get("ratio", 1.0)
        if vol_ratio > 1.5:
            score += 0.5
            reasons.append(f"거래량{vol_ratio:.1f}x")

        if score < 2.5:
            return None

        base_q = min(0.8, 0.4 + score * 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(
            df, curr_close, "SHORT",
            sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
            key_levels=kl, adx=adx,
        )

        return Signal(
            strategy="UPBIT_TOMMY_MACD",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=f"[Tommy MACD {score:.1f}pt] " + " | ".join(reasons),
        )

    return None

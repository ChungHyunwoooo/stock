"""Tommy BB + RSI 강화 전략.

TommyTradingTV 강의 기반:
- RMA 200 기반 볼린저밴드 (기본 SMA 20이 아님)
- RSI 캔들 (라인이 아님) — 연속 꼬리 패턴
- 4가지 동시 조건: BB 돌파 + RSI 극단 + RSI 다이버전스 + RSI 5연속 꼬리

기존 upbit_scanner.py의 scan_* 인터페이스를 따름:
  (df, symbol, config, context) -> Signal | None
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib

from engine.alerts.discord import Signal


def _calc_rma(series: np.ndarray, period: int) -> np.ndarray:
    """RMA (Running Moving Average) = Wilder's smoothing.

    RMA(t) = (RMA(t-1) * (period-1) + value(t)) / period
    Same as talib's RSI internal smoothing.
    """
    rma = np.full_like(series, np.nan, dtype=float)
    if len(series) < period:
        return rma

    # SMA seed
    rma[period - 1] = np.mean(series[:period])
    alpha = 1.0 / period
    for i in range(period, len(series)):
        rma[i] = rma[i - 1] * (1 - alpha) + series[i] * alpha
    return rma


def _rsi_candle_wicks(close: np.ndarray, rsi_period: int = 14) -> dict:
    """RSI를 캔들처럼 해석하여 꼬리(wick) 패턴을 분석.

    RSI OHLC = RSI를 각 봉의 시가/고가/저가/종가로 매핑:
    - RSI open = 이전 봉의 RSI close
    - RSI close = 현재 RSI
    - RSI high/low = 해당 봉 내 최대/최소 RSI (근사: max/min of RSI, prev RSI)

    5연속 하단 꼬리 = RSI가 계속 30 이하 찍지만 반등 = 매수 신호
    5연속 상단 꼬리 = RSI가 계속 70 이상 찍지만 하락 = 매도 신호
    """
    rsi = talib.RSI(close, timeperiod=rsi_period)

    consecutive_lower_wicks = 0
    consecutive_upper_wicks = 0

    for i in range(-5, 0):
        if np.isnan(rsi[i]) or np.isnan(rsi[i - 1]):
            return {"lower_wicks": 0, "upper_wicks": 0}

        rsi_open = float(rsi[i - 1])
        rsi_close = float(rsi[i])
        rsi_body_low = min(rsi_open, rsi_close)
        rsi_body_high = max(rsi_open, rsi_close)

        # 하단 꼬리: RSI가 30 이하 영역까지 내려갔다가 body는 그 위
        rsi_low_approx = min(rsi_open, rsi_close) - abs(rsi_close - rsi_open) * 0.3
        if rsi_low_approx < 30 and rsi_body_low > 28:
            consecutive_lower_wicks += 1
        elif rsi_close < 35 and rsi_open < 35:
            # 과매도 영역에 있으면서 반등 시도
            if rsi_close > rsi_open:
                consecutive_lower_wicks += 1

        # 상단 꼬리: RSI가 70 이상 영역까지 올라갔다가 body는 그 아래
        rsi_high_approx = max(rsi_open, rsi_close) + abs(rsi_close - rsi_open) * 0.3
        if rsi_high_approx > 70 and rsi_body_high < 72:
            consecutive_upper_wicks += 1
        elif rsi_close > 65 and rsi_open > 65:
            if rsi_close < rsi_open:
                consecutive_upper_wicks += 1

    return {
        "lower_wicks": consecutive_lower_wicks,
        "upper_wicks": consecutive_upper_wicks,
    }


def _detect_rsi_divergence(
    close: np.ndarray, rsi: np.ndarray, lookback: int = 20
) -> dict:
    """RSI 다이버전스 감지.

    Bullish: 가격 저점 하락 + RSI 저점 상승
    Bearish: 가격 고점 상승 + RSI 고점 하락
    """
    if len(close) < lookback or len(rsi) < lookback:
        return {"bullish": False, "bearish": False}

    half = lookback // 2
    p1 = close[-lookback:-half]
    p2 = close[-half:]
    r1 = rsi[-lookback:-half]
    r2 = rsi[-half:]

    # NaN 체크
    if np.isnan(r1).any() or np.isnan(r2).any():
        return {"bullish": False, "bearish": False}

    bullish = (float(np.min(p2)) < float(np.min(p1))
               and float(np.min(r2)) > float(np.min(r1)))
    bearish = (float(np.max(p2)) > float(np.max(p1))
               and float(np.max(r2)) < float(np.max(r1)))

    return {"bullish": bullish, "bearish": bearish}


def scan_tommy_bb_rsi(
    df: pd.DataFrame,
    symbol: str,
    config=None,
    context: dict | None = None,
) -> Signal | None:
    """Tommy BB + RSI 강화 전략.

    Tommy 강의 핵심 4가지 동시 조건:
    1. RMA 200 기반 BB 돌파 (가격이 밴드 밖으로 나갔다 복귀)
    2. RSI 극단 영역 (< 30 또는 > 70)
    3. RSI 다이버전스
    4. RSI 캔들 5연속 꼬리 (매수압/매도압 흡수)

    LONG: BB 하단 돌파 후 복귀 + RSI < 30 + RSI 상승 다이버전스 + 하단 꼬리 5연속
    SHORT: BB 상단 돌파 후 복귀 + RSI > 70 + RSI 하락 다이버전스 + 상단 꼬리 5연속
    """
    from engine.strategy.upbit_scanner import (
        UpbitScannerConfig,
        calc_dynamic_levels,
    )
    from engine.analysis import calc_confidence_v2

    cfg = config or UpbitScannerConfig()
    rma_period = 200

    if len(df) < rma_period + 20:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    curr_close = float(close[-1])
    prev_close = float(close[-2])

    # --- RMA 200 기반 볼린저밴드 ---
    rma = _calc_rma(close, rma_period)
    if np.isnan(rma[-1]):
        return None

    # BB = RMA ± 2 * StdDev(close, 200)
    std_period = rma_period
    std_vals = pd.Series(close).rolling(std_period).std().values
    if np.isnan(std_vals[-1]):
        return None

    bb_upper = rma[-1] + 2 * std_vals[-1]
    bb_lower = rma[-1] - 2 * std_vals[-1]
    bb_mid = rma[-1]

    prev_bb_upper = rma[-2] + 2 * std_vals[-2] if not np.isnan(rma[-2]) else bb_upper
    prev_bb_lower = rma[-2] - 2 * std_vals[-2] if not np.isnan(rma[-2]) else bb_lower

    # --- RSI ---
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    if np.isnan(rsi[-1]):
        return None
    curr_rsi = float(rsi[-1])

    # --- Context ---
    ctx = context or {}
    kl = ctx.get("key_levels", {})
    candle = ctx.get("candle", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})

    # --- 4가지 조건 체크 ---

    # 조건 1: BB 돌파 후 복귀
    # LONG: 이전 봉이 BB 하단 아래였다가 현재 봉이 다시 안으로 들어옴
    bb_lower_breach_recover = (prev_close < prev_bb_lower and curr_close >= bb_lower)
    # 또는 현재가가 BB 하단 바로 위 (5% 밴드 내)
    bb_lower_near = (curr_close - bb_lower) / (bb_upper - bb_lower) < 0.05 if bb_upper > bb_lower else False

    bb_upper_breach_recover = (prev_close > prev_bb_upper and curr_close <= bb_upper)
    bb_upper_near = (bb_upper - curr_close) / (bb_upper - bb_lower) < 0.05 if bb_upper > bb_lower else False

    # 조건 2: RSI 극단
    rsi_oversold = curr_rsi < 30
    rsi_overbought = curr_rsi > 70

    # 조건 3: RSI 다이버전스
    div = _detect_rsi_divergence(close, rsi)

    # 조건 4: RSI 캔들 꼬리 패턴
    wick = _rsi_candle_wicks(close, cfg.rsi_period)

    # --- LONG 신호 ---
    score = 0.0
    reasons = []

    if (bb_lower_breach_recover or bb_lower_near) and rsi_oversold:
        if kl.get("at_resistance", False):
            return None

        score += 1.5
        if bb_lower_breach_recover:
            reasons.append("BB하단돌파복귀(RMA200)")
        else:
            reasons.append("BB하단근접(RMA200)")

        score += 1.0
        reasons.append(f"RSI과매도({curr_rsi:.0f})")

        if div["bullish"]:
            score += 1.5
            reasons.append("RSI상승다이버전스")

        if wick["lower_wicks"] >= 4:
            score += 1.5
            reasons.append(f"RSI하단꼬리{wick['lower_wicks']}연속")
        elif wick["lower_wicks"] >= 3:
            score += 0.8
            reasons.append(f"RSI하단꼬리{wick['lower_wicks']}연속")

        # 보조 조건
        if candle.get("bullish_engulfing") or candle.get("bullish_pin_bar"):
            score += 0.5
            reasons.append("반전캔들")

        if kl.get("at_support", False):
            score += 0.5
            reasons.append("지지선")

        # Tommy 원래 조건: 4가지 동시 충족 시 고신뢰
        # 일부만 충족 시에도 3점 이상이면 시그널 발생
        if score < 3.0:
            return None

        base_q = min(0.85, 0.4 + score * 0.08)
        # 4가지 모두 충족 시 보너스
        if div["bullish"] and wick["lower_wicks"] >= 4:
            base_q = min(0.9, base_q + 0.1)

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(
            df, curr_close, "LONG",
            sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
            key_levels=kl, adx=adx,
        )

        return Signal(
            strategy="UPBIT_TOMMY_BB_RSI",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=f"[Tommy BB+RSI {score:.1f}pt] " + " | ".join(reasons),
        )

    # --- SHORT 신호 ---
    score = 0.0
    reasons = []

    if (bb_upper_breach_recover or bb_upper_near) and rsi_overbought:
        if kl.get("at_support", False):
            return None

        score += 1.5
        if bb_upper_breach_recover:
            reasons.append("BB상단돌파복귀(RMA200)")
        else:
            reasons.append("BB상단근접(RMA200)")

        score += 1.0
        reasons.append(f"RSI과매수({curr_rsi:.0f})")

        if div["bearish"]:
            score += 1.5
            reasons.append("RSI하락다이버전스")

        if wick["upper_wicks"] >= 4:
            score += 1.5
            reasons.append(f"RSI상단꼬리{wick['upper_wicks']}연속")
        elif wick["upper_wicks"] >= 3:
            score += 0.8
            reasons.append(f"RSI상단꼬리{wick['upper_wicks']}연속")

        if candle.get("bearish_engulfing") or candle.get("bearish_pin_bar"):
            score += 0.5
            reasons.append("반전캔들")

        if kl.get("at_resistance", False):
            score += 0.5
            reasons.append("저항선")

        if score < 3.0:
            return None

        base_q = min(0.85, 0.4 + score * 0.08)
        if div["bearish"] and wick["upper_wicks"] >= 4:
            base_q = min(0.9, base_q + 0.1)

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(
            df, curr_close, "SHORT",
            sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
            key_levels=kl, adx=adx,
        )

        return Signal(
            strategy="UPBIT_TOMMY_BB_RSI",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=f"[Tommy BB+RSI {score:.1f}pt] " + " | ".join(reasons),
        )

    return None

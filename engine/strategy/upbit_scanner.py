"""Upbit KRW Day Trading Scanner — EMA + RSI + VWAP 5분 스캘핑.

YouTube에서 가장 인기 있는 "83% Win Rate 5-Minute Scalping" 전략 기반:
- EMA 9/21 크로스오버 (추세 전환 감지)
- RSI 14 (과매수/과매도 필터)
- VWAP (스마트머니 방향 필터)
- 거래량 확인 (1.5x 이상)

30초마다 Upbit KRW 마켓 전 종목 자동 스캔.
새로운 시그널만 Discord로 차트 이미지와 함께 알림.

Sources:
- https://daviddtech.medium.com/83-win-rate-5-minute-ultimate-scalping-trading-strategy
- https://provencrypto.com/crypto-trading-strategy-with-ema-rsi/
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplfinance as mpf
import numpy as np
import pandas as pd
import pyupbit
import talib

from engine.alerts.discord import Signal
from engine.analysis import build_context, calc_confidence_v2
from engine.data.upbit_ws import UpbitWebSocketManager
from engine.data.upbit_cache import OHLCVCacheManager
from engine.strategy.upbit_mtf import analyze_mtf, mtf_filter_signal, TrendContext

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "upbit_scanner.json"
SENT_SIGNALS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "upbit_sent.json"

# ---------------------------------------------------------------------------
# Upbit KRW 종목 목록
# ---------------------------------------------------------------------------

# 시가총액 상위 + 거래량 활발한 종목
DEFAULT_SYMBOLS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-MATIC",
    "KRW-BCH", "KRW-ETC", "KRW-ATOM", "KRW-APT", "KRW-ARB",
    "KRW-OP", "KRW-SUI", "KRW-SEI", "KRW-NEAR", "KRW-AAVE",
]


# ---------------------------------------------------------------------------
# Scanner Config
# ---------------------------------------------------------------------------

@dataclass
class UpbitScannerConfig:
    enabled: bool = True
    scan_interval_sec: int = 30
    symbols: list[str] = field(default_factory=list)  # empty = auto-scan all active KRW coins
    # Strategy params
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_long_min: float = 40.0      # RSI > 40 for LONG (not oversold bounce yet)
    rsi_long_max: float = 70.0      # RSI < 70 for LONG (not overbought)
    rsi_short_min: float = 30.0     # RSI > 30 for SHORT (not oversold)
    rsi_short_max: float = 60.0     # RSI < 60 for SHORT
    vol_mult: float = 1.5           # Volume > 1.5x average
    # Risk
    sl_pct: float = 0.01            # 1% SL
    tp1_pct: float = 0.01           # 1% TP1 (1:1 R:R)
    tp2_pct: float = 0.02           # 2% TP2 (2:1 R:R)
    tp3_pct: float = 0.03           # 3% TP3 (3:1 R:R)
    leverage: int = 1               # Upbit spot = 1x
    # Strategy toggles
    enable_ema_rsi_vwap: bool = True
    enable_supertrend: bool = True
    enable_macd_div: bool = True
    enable_stoch_rsi: bool = True
    enable_fibonacci: bool = True
    enable_ichimoku: bool = True
    enable_early_pump: bool = True
    # New strategies
    enable_smc: bool = True
    enable_hidden_div: bool = True
    enable_bb_rsi_stoch: bool = True
    enable_mega_pump: bool = True
    enable_tommy_macd: bool = True
    enable_tommy_bb_rsi: bool = True
    # --- Strategy-specific indicator params (하드코딩 → config 이관) ---
    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0
    # Supertrend
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # StochRSI
    stoch_period: int = 14
    stoch_k: int = 3
    stoch_d: int = 3
    # Ichimoku
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou: int = 52
    # ADX / ATR
    adx_period: int = 14
    atr_period: int = 14
    # SL/TP mode
    sl_mode: str = "hybrid"     # "atr" | "structure" | "hybrid"
    tp_mode: str = "staged"     # "fixed" | "staged"
    # Alert
    cooldown_sec: int = 600         # 같은 종목 10분 쿨다운
    send_chart: bool = True
    # MTF + WebSocket + Parallel
    enable_mtf: bool = True         # 멀티타임프레임 추세 필터
    enable_daily_filter: bool = True   # 일봉 사이클 필터
    enable_weekly_filter: bool = True  # 주봉 사이클 필터 (soft)
    ws_enabled: bool = True         # WebSocket 실시간 모드
    parallel_fetch: bool = True     # 병렬 OHLCV fetch
    # Timeframe toggles
    enable_tf_4h: bool = True
    enable_tf_1h: bool = True
    enable_tf_30m: bool = True
    enable_tf_5m: bool = True

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> UpbitScannerConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                known = {f.name for f in cls.__dataclass_fields__.values()}
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception as e:
                logger.warning("Failed to load upbit scanner config: %s", e)
        return cls()


# ---------------------------------------------------------------------------
# Upbit KRW Tick Size (호가 단위)
# ---------------------------------------------------------------------------

def _upbit_tick(price: float) -> float:
    """Return the Upbit KRW market tick size for a given price."""
    if price >= 2_000_000:
        return 1000
    elif price >= 1_000_000:
        return 500
    elif price >= 500_000:
        return 100
    elif price >= 100_000:
        return 50
    elif price >= 10_000:
        return 10
    elif price >= 1_000:
        return 1
    elif price >= 100:
        return 0.1
    elif price >= 10:
        return 0.01
    elif price >= 1:
        return 0.001
    else:
        return 0.0001


def _tick_round(price: float, direction: str = "nearest") -> float:
    """Round price to Upbit tick size.

    direction: 'nearest', 'down' (for SL on LONG), 'up' (for SL on SHORT)
    """
    tick = _upbit_tick(price)
    if direction == "down":
        return int(price / tick) * tick
    elif direction == "up":
        import math
        return math.ceil(price / tick) * tick
    else:
        return round(price / tick) * tick


# ---------------------------------------------------------------------------
# VWAP Calculation
# ---------------------------------------------------------------------------

def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate VWAP (Volume Weighted Average Price)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol
    return vwap


# ---------------------------------------------------------------------------
# Strategy: EMA + RSI + VWAP Confluence
# ---------------------------------------------------------------------------

def scan_ema_rsi_vwap(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """EMA 되돌림 + 컨플루언스 전략 (v2).

    LONG 조건:
    1. EMA9 > EMA21 3봉 이상 지속 (추세 확립)
    2. EMA21 되돌림 + 바운스 확인
    3. 종가 > VWAP
    4. RSI 40-65 + RSI 상승중
    5. ADX 추세 확인 + DI+ > DI-
    6. 거래량 ≥ 1.2x + 다이버전스 없음

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()

    if len(df) < 50:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    # Indicators
    ema_fast = talib.EMA(close, timeperiod=cfg.ema_fast)
    ema_slow = talib.EMA(close, timeperiod=cfg.ema_slow)
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    vwap = _calc_vwap(df).values

    # Volume check
    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0

    # Current values
    curr_close = float(close[-1])
    curr_rsi = float(rsi[-1])
    prev_rsi = float(rsi[-2]) if not np.isnan(rsi[-2]) else curr_rsi
    curr_vwap = float(vwap[-1])

    # Analysis context
    ctx = context or {}
    pb = ctx.get("pullback", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # EMA trend persistence (3봉 이상 유지)
    ema_bullish_count = 0
    ema_bearish_count = 0
    for i in range(-1, -6, -1):
        if not np.isnan(ema_fast[i]) and not np.isnan(ema_slow[i]):
            if ema_fast[i] > ema_slow[i]:
                ema_bullish_count += 1
            elif ema_fast[i] < ema_slow[i]:
                ema_bearish_count += 1
            else:
                break

    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    # --- LONG ---
    if (ema_bullish_count >= 3
            and (pb.get("is_pullback_to_ema") or pb.get("bounce_confirmed"))
            and curr_close > curr_vwap
            and 40 < curr_rsi < 65 and curr_rsi > prev_rsi
            and adx.get("is_trending", False) and adx.get("trend_direction") == "BULLISH"
            and vol_ratio >= 1.2
            and not vol_ctx.get("vol_price_divergence", False)
            and is_bullish):

        base_q = min(1.0, 0.5 + (vol_ratio - 1) * 0.2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"EMA Pullback"]
        if structure.get("trend") == "BULLISH":
            reasons.append(f"구조:BULLISH(HH{structure.get('hh_count', 0)})")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if kl.get("at_support"):
            reasons.append("지지선근접")
        if candle.get("bullish_engulfing") or candle.get("bullish_pin_bar"):
            reasons.append("캔들확인")
        if vol_ctx.get("obv_trend") == "RISING":
            reasons.append("OBV↑")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_EMA_RSI_VWAP",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    if (ema_bearish_count >= 3
            and curr_close < curr_vwap
            and 35 < curr_rsi < 60 and curr_rsi < prev_rsi
            and adx.get("is_trending", False) and adx.get("trend_direction") == "BEARISH"
            and vol_ratio >= 1.2
            and not vol_ctx.get("vol_price_divergence", False)
            and is_bearish):

        base_q = min(1.0, 0.5 + (vol_ratio - 1) * 0.2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"EMA Pullback SHORT"]
        if structure.get("trend") == "BEARISH":
            reasons.append(f"구조:BEARISH")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if vol_ctx.get("obv_trend") == "FALLING":
            reasons.append("OBV↓")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_EMA_RSI_VWAP",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Supertrend (ATR-based trend following)
# ---------------------------------------------------------------------------

def scan_supertrend(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    period: int | None = None,
    multiplier: float | None = None,
    context: dict | None = None,
) -> Signal | None:
    """슈퍼트렌드 + ADX + 시장구조 (v2).

    LONG 조건:
    1. 슈퍼트렌드 방향 전환 (빨강→초록)
    2. 시장구조 ≠ BEARISH
    3. ADX > 18
    4. 거래량 ≥ 1.3x + OBV 상승
    5. 양봉 + 클라이맥스 아님

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()
    period = period if period is not None else cfg.supertrend_period
    multiplier = multiplier if multiplier is not None else cfg.supertrend_multiplier
    if len(df) < period + 20:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    atr = talib.ATR(high, low, close, timeperiod=period)
    hl2 = (high + low) / 2

    # Calculate Supertrend
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    n = len(close)
    supertrend = np.zeros(n)
    direction = np.zeros(n)  # 1 = up (bullish), -1 = down (bearish)

    supertrend[period] = upper_band[period]
    direction[period] = -1

    for i in range(period + 1, n):
        if close[i] > upper_band[i - 1]:
            direction[i] = 1
        elif close[i] < lower_band[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        if direction[i] == 1:
            supertrend[i] = max(lower_band[i], supertrend[i - 1]) if direction[i - 1] == 1 else lower_band[i]
        else:
            supertrend[i] = min(upper_band[i], supertrend[i - 1]) if direction[i - 1] == -1 else upper_band[i]

    # Signal: direction change
    curr_dir = direction[-1]
    prev_dir = direction[-2]
    curr_close = float(close[-1])

    # Analysis context
    ctx = context or {}
    structure = ctx.get("structure", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    atr_pct = float(atr[-1]) / curr_close * 100 if curr_close > 0 else 0

    if (prev_dir == -1 and curr_dir == 1
            and structure.get("trend") != "BEARISH"
            and adx.get("adx", 0) > 18
            and vol_ctx.get("vol_ratio", 0) >= 1.3
            and vol_ctx.get("obv_trend") == "RISING"
            and is_bullish
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + atr_pct * 2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"Supertrend 전환↑"]
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ctx.get('vol_ratio', 0):.1f}x")
        if vol_ctx.get("obv_trend") == "RISING":
            reasons.append("OBV↑")

        return Signal(
            strategy="UPBIT_SUPERTREND",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    if (prev_dir == 1 and curr_dir == -1
            and structure.get("trend") != "BULLISH"
            and adx.get("adx", 0) > 18
            and vol_ctx.get("vol_ratio", 0) >= 1.3
            and vol_ctx.get("obv_trend") == "FALLING"
            and is_bearish
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + atr_pct * 2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"Supertrend 전환↓"]
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ctx.get('vol_ratio', 0):.1f}x")
        if vol_ctx.get("obv_trend") == "FALLING":
            reasons.append("OBV↓")

        return Signal(
            strategy="UPBIT_SUPERTREND",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: MACD Divergence
# ---------------------------------------------------------------------------

def scan_macd_divergence(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    fast: int | None = None,
    slow: int | None = None,
    signal_period: int | None = None,
    lookback: int = 20,
    context: dict | None = None,
) -> Signal | None:
    """MACD 다이버전스 @ 키레벨 (v2).

    Bullish Divergence 조건:
    1. 피봇 기반 다이버전스 (가격↓ MACD↑)
    2. 지지선에서의 다이버전스
    3. 히스토그램 0선 돌파 또는 3봉 연속 약화
    4. 두번째 저점 거래량 < 첫번째 (매도 소진)
    5. 장악형/핀바 캔들
    6. RSI < 40

    Bearish Divergence (미러)
    """
    cfg = config or UpbitScannerConfig()
    fast = fast if fast is not None else cfg.macd_fast
    slow = slow if slow is not None else cfg.macd_slow
    signal_period = signal_period if signal_period is not None else cfg.macd_signal
    if len(df) < slow + lookback:
        return None

    close = df["close"].values
    vol = df["volume"].values
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    macd_line, signal_line, hist = talib.MACD(close, fastperiod=fast,
                                               slowperiod=slow,
                                               signalperiod=signal_period)

    curr_close = float(close[-1])
    curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50.0
    recent_close = close[-lookback:]
    recent_macd = macd_line[-lookback:]
    recent_vol = vol[-lookback:]

    if np.isnan(recent_macd).any():
        return None

    # Analysis context
    ctx = context or {}
    kl = ctx.get("key_levels", {})
    candle = ctx.get("candle", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})

    half = lookback // 2
    early_region = recent_close[:half]
    late_region = recent_close[half:]

    early_price_min = float(np.min(early_region))
    late_price_min = float(np.min(late_region))
    early_macd_min = float(np.min(recent_macd[:half]))
    late_macd_min = float(np.min(recent_macd[half:]))

    early_price_max = float(np.max(early_region))
    late_price_max = float(np.max(late_region))
    early_macd_max = float(np.max(recent_macd[:half]))
    late_macd_max = float(np.max(recent_macd[half:]))

    # Volume at divergence points
    early_vol_at_min = float(recent_vol[np.argmin(early_region)])
    late_vol_at_min = float(recent_vol[half + np.argmin(late_region)])

    # MACD histogram turning
    hist_turning_up = float(hist[-1]) > float(hist[-2]) and float(hist[-2]) > float(hist[-3])
    hist_turning_down = float(hist[-1]) < float(hist[-2]) and float(hist[-2]) < float(hist[-3])
    hist_cross_zero_up = float(hist[-1]) > 0 and float(hist[-2]) <= 0
    hist_cross_zero_down = float(hist[-1]) < 0 and float(hist[-2]) >= 0

    base_q = min(1.0, 0.55 + abs(float(hist[-1])) / curr_close * 500)

    # --- Bullish divergence @ support ---
    if (late_price_min < early_price_min
            and late_macd_min > early_macd_min
            and (hist_turning_up or hist_cross_zero_up)
            and kl.get("at_support", False)
            and late_vol_at_min < early_vol_at_min  # 매도 소진
            and (candle.get("bullish_engulfing") or candle.get("bullish_pin_bar") or hist_cross_zero_up)
            and curr_rsi < 40):

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["MACD 상승 다이버전스"]
        reasons.append("지지선확인")
        if candle.get("bullish_engulfing"):
            reasons.append("장악형캔들")
        elif candle.get("bullish_pin_bar"):
            reasons.append("핀바")
        reasons.append(f"RSI:{curr_rsi:.0f}")
        reasons.append("매도소진")

        return Signal(
            strategy="UPBIT_MACD_DIV",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- Bearish divergence @ resistance ---
    if (late_price_max > early_price_max
            and late_macd_max < early_macd_max
            and (hist_turning_down or hist_cross_zero_down)
            and kl.get("at_resistance", False)
            and (candle.get("bearish_engulfing") or candle.get("bearish_pin_bar") or hist_cross_zero_down)
            and curr_rsi > 60):

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["MACD 하락 다이버전스"]
        reasons.append("저항선확인")
        if candle.get("bearish_engulfing"):
            reasons.append("장악형캔들")
        elif candle.get("bearish_pin_bar"):
            reasons.append("핀바")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_MACD_DIV",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Stochastic RSI
# ---------------------------------------------------------------------------

def scan_stoch_rsi(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    rsi_period: int | None = None,
    stoch_period: int | None = None,
    k_period: int | None = None,
    d_period: int | None = None,
    context: dict | None = None,
) -> Signal | None:
    """StochRSI @ 지지선 + BB (v2).

    LONG 조건:
    1. K > D 크로스 + prev_K < 15
    2. 지지선 근처 (필수)
    3. %B < 0.2 또는 BB 스퀴즈
    4. 시장구조 ≠ BEARISH
    5. ADX < 30 (과열된 추세 아닌 것)
    6. 양봉/핀바 + 클라이맥스 아님

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()
    rsi_period = rsi_period if rsi_period is not None else cfg.rsi_period
    stoch_period = stoch_period if stoch_period is not None else cfg.stoch_period
    k_period = k_period if k_period is not None else cfg.stoch_k
    d_period = d_period if d_period is not None else cfg.stoch_d
    if len(df) < rsi_period + stoch_period + 10:
        return None

    close = df["close"].values
    rsi = talib.RSI(close, timeperiod=rsi_period)

    fastk, fastd = talib.STOCHRSI(close, timeperiod=stoch_period,
                                    fastk_period=k_period,
                                    fastd_period=d_period)

    if np.isnan(fastk[-1]) or np.isnan(fastd[-1]):
        return None

    curr_k = float(fastk[-1])
    curr_d = float(fastd[-1])
    prev_k = float(fastk[-2])
    prev_d = float(fastd[-2])
    curr_close = float(close[-1])
    curr_rsi = float(rsi[-1])

    # Analysis context
    ctx = context or {}
    kl = ctx.get("key_levels", {})
    bb = ctx.get("bb", {})
    structure = ctx.get("structure", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})

    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]
    is_bearish = last["close"] < last["open"]

    # --- LONG ---
    if (prev_k <= prev_d and curr_k > curr_d
            and prev_k < 15
            and kl.get("at_support", False)
            and (bb.get("pct_b", 0.5) < 0.2 or bb.get("is_squeeze", False))
            and structure.get("trend") != "BEARISH"
            and adx.get("adx", 0) < 30
            and (is_bullish or candle.get("bullish_pin_bar", False))
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + abs(curr_k - curr_d) / 100 * 2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"StochRSI 과매도→반등 prevK:{prev_k:.0f}→{curr_k:.0f}"]
        reasons.append("지지선확인")
        if bb.get("is_squeeze"):
            reasons.append("BB스퀴즈")
        else:
            reasons.append(f"%B:{bb.get('pct_b', 0):.2f}")
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_STOCH_RSI",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    if (prev_k >= prev_d and curr_k < curr_d
            and prev_k > 85
            and kl.get("at_resistance", False)
            and (bb.get("pct_b", 0.5) > 0.8 or bb.get("is_squeeze", False))
            and structure.get("trend") != "BULLISH"
            and adx.get("adx", 0) < 30
            and (is_bearish or candle.get("bearish_pin_bar", False))
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + abs(curr_k - curr_d) / 100 * 2)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"StochRSI 과매수→하락 prevK:{prev_k:.0f}→{curr_k:.0f}"]
        reasons.append("저항선확인")
        if bb.get("is_squeeze"):
            reasons.append("BB스퀴즈")
        else:
            reasons.append(f"%B:{bb.get('pct_b', 0):.2f}")
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_STOCH_RSI",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Fibonacci Retracement
# ---------------------------------------------------------------------------

def scan_fibonacci(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    lookback: int = 100,
    context: dict | None = None,
) -> Signal | None:
    """피보나치 골든존 + 되돌림 품질 (v2).

    LONG 조건:
    1. 시장구조 BULLISH + ADX > 20
    2. 스윙포인트를 structure에서 가져옴
    3. 골든존 38.2%-61.8% 내 위치
    4. 거래량 추세 FALLING (건강한 풀백)
    5. EMA21 근접 (0.5% 이내)
    6. 장악형/핀바 캔들
    7. RSI 30-60

    SHORT (미러)
    """
    cfg = config or UpbitScannerConfig()
    if len(df) < lookback:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    # Analysis context
    ctx = context or {}
    structure = ctx.get("structure", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})
    pb = ctx.get("pullback", {})

    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50.0
    curr_close = float(close[-1])

    # Use structure swing points if available, fallback to raw
    swing_high = structure.get("last_swing_high", 0)
    swing_low = structure.get("last_swing_low", 0)
    if swing_high == 0 or swing_low == 0:
        recent = close[-lookback:]
        swing_high = float(np.max(recent))
        swing_low = float(np.min(recent))

    diff = swing_high - swing_low
    if diff <= 0 or diff / swing_low < 0.02:
        return None

    # Fibonacci levels
    fib_382 = swing_high - diff * 0.382
    fib_500 = swing_high - diff * 0.500
    fib_618 = swing_high - diff * 0.618

    # EMA21 proximity
    ema21 = talib.EMA(close, timeperiod=21)
    ema_near = False
    if not np.isnan(ema21[-1]):
        ema_near = abs(curr_close - float(ema21[-1])) / curr_close < 0.005

    # Golden zone check (38.2% - 61.8%)
    in_golden_zone = fib_618 <= curr_close <= fib_382
    tol = curr_close * 0.003

    is_bullish = df.iloc[-1]["close"] > df.iloc[-1]["open"]
    is_bearish = df.iloc[-1]["close"] < df.iloc[-1]["open"]

    # --- LONG: 상승 추세에서 골든존 되돌림 ---
    if (structure.get("trend") == "BULLISH"
            and adx.get("adx", 0) > 20
            and in_golden_zone
            and vol_ctx.get("vol_trend") == "FALLING"  # 건강한 풀백
            and ema_near
            and (candle.get("bullish_engulfing") or candle.get("bullish_pin_bar") or is_bullish)
            and 30 < curr_rsi < 60):

        # Which fib level closest?
        dist_382 = abs(curr_close - fib_382)
        dist_500 = abs(curr_close - fib_500)
        dist_618 = abs(curr_close - fib_618)
        min_dist = min(dist_382, dist_500, dist_618)
        if min_dist == dist_618:
            fib_label, fib_val = "61.8%", fib_618
        elif min_dist == dist_500:
            fib_label, fib_val = "50%", fib_500
        else:
            fib_label, fib_val = "38.2%", fib_382

        base_q = min(1.0, 0.6 + (swing_high - curr_close) / diff * 0.3)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"Fib {fib_label} 골든존"]
        reasons.append(f"구조:BULLISH(HH{structure.get('hh_count', 0)})")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if ema_near:
            reasons.append("EMA21근접")
        if candle.get("bullish_engulfing"):
            reasons.append("장악형캔들")
        elif candle.get("bullish_pin_bar"):
            reasons.append("핀바")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_FIBONACCI",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT: 하락 추세에서 되돌림 저항 ---
    fib_382_up = swing_low + diff * 0.382
    fib_500_up = swing_low + diff * 0.500
    in_short_zone = fib_382_up <= curr_close <= fib_500_up

    if (structure.get("trend") == "BEARISH"
            and adx.get("adx", 0) > 20
            and in_short_zone
            and vol_ctx.get("vol_trend") == "FALLING"
            and (candle.get("bearish_engulfing") or candle.get("bearish_pin_bar") or is_bearish)
            and 40 < curr_rsi < 70):

        base_q = min(1.0, 0.6 + (curr_close - swing_low) / diff * 0.3)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"Fib 38.2% 저항 반락"]
        reasons.append(f"구조:BEARISH")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if candle.get("bearish_engulfing"):
            reasons.append("장악형캔들")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="UPBIT_FIBONACCI",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Ichimoku Cloud
# ---------------------------------------------------------------------------

def scan_ichimoku(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    tenkan_period: int | None = None,
    kijun_period: int | None = None,
    senkou_period: int | None = None,
    context: dict | None = None,
) -> Signal | None:
    """일목 5요소 완전체 (v2).

    LONG 조건:
    1. 종가 > 구름 상단
    2. 전환선 > 기준선 (크로스 또는 기준선 되돌림 반등)
    3. 치코스팬: 현재가 > 26봉 전 가격 + 구름 상단
    4. 미래 구름: 선행스팬A > 선행스팬B
    5. ADX 추세 + 거래량 ≥ 1.2x
    6. 구름 내부 시그널 차단

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()
    tenkan_period = tenkan_period if tenkan_period is not None else cfg.ichimoku_tenkan
    kijun_period = kijun_period if kijun_period is not None else cfg.ichimoku_kijun
    senkou_period = senkou_period if senkou_period is not None else cfg.ichimoku_senkou
    if len(df) < senkou_period + 26:
        return None

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    def midpoint(h, l, period):
        """Period high/low midpoint (Ichimoku-style)."""
        result = np.full(len(h), np.nan)
        for i in range(period - 1, len(h)):
            result[i] = (np.max(h[i - period + 1:i + 1]) + np.min(l[i - period + 1:i + 1])) / 2
        return result

    tenkan = midpoint(high, low, tenkan_period)   # 전환선
    kijun = midpoint(high, low, kijun_period)     # 기준선
    senkou_a = (tenkan + kijun) / 2               # 선행스팬 A
    senkou_b = midpoint(high, low, senkou_period) # 선행스팬 B

    if np.isnan(tenkan[-1]) or np.isnan(kijun[-1]) or np.isnan(senkou_a[-1]) or np.isnan(senkou_b[-1]):
        return None

    curr_close = float(close[-1])
    curr_tenkan = float(tenkan[-1])
    curr_kijun = float(kijun[-1])
    prev_tenkan = float(tenkan[-2])
    prev_kijun = float(kijun[-2])
    cloud_top = max(float(senkou_a[-1]), float(senkou_b[-1]))
    cloud_bottom = min(float(senkou_a[-1]), float(senkou_b[-1]))

    # Analysis context
    ctx = context or {}
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # 구름 내부 = 시그널 차단
    if cloud_bottom <= curr_close <= cloud_top:
        return None

    # 치코스팬: 현재가 vs 26봉 전 가격
    chikou_idx = -26
    chikou_ok_bull = False
    chikou_ok_bear = False
    if abs(chikou_idx) < len(close):
        price_26ago = float(close[chikou_idx])
        # 26봉 전 구름
        cloud_top_26 = max(float(senkou_a[chikou_idx]), float(senkou_b[chikou_idx])) if not np.isnan(senkou_a[chikou_idx]) else 0
        cloud_bottom_26 = min(float(senkou_a[chikou_idx]), float(senkou_b[chikou_idx])) if not np.isnan(senkou_b[chikou_idx]) else 0
        chikou_ok_bull = curr_close > price_26ago and curr_close > cloud_top_26
        chikou_ok_bear = curr_close < price_26ago and curr_close < cloud_bottom_26

    # 미래 구름 방향
    future_cloud_bullish = float(senkou_a[-1]) > float(senkou_b[-1])
    future_cloud_bearish = float(senkou_a[-1]) < float(senkou_b[-1])

    # 전환선/기준선 관계 (크로스 또는 기준선 되돌림 반등)
    tk_cross_bull = (prev_tenkan <= prev_kijun and curr_tenkan > curr_kijun)
    tk_above = curr_tenkan > curr_kijun
    tk_cross_bear = (prev_tenkan >= prev_kijun and curr_tenkan < curr_kijun)
    tk_below = curr_tenkan < curr_kijun

    cloud_thickness = (cloud_top - cloud_bottom) / curr_close * 100 if curr_close > 0 else 0

    # 구름 근접도: 구름 경계 대비 현재가 거리 (%)
    dist_from_cloud_top = (curr_close - cloud_top) / curr_close * 100 if curr_close > 0 else 999
    dist_from_cloud_bottom = (cloud_bottom - curr_close) / curr_close * 100 if curr_close > 0 else 999

    # --- LONG ---
    # 구름 상단 돌파 직후 (2% 이내) + TK 크로스 우선, tk_above는 구름 근접시만
    cloud_proximity_long = dist_from_cloud_top < 2.0
    tk_condition_long = tk_cross_bull or (tk_above and cloud_proximity_long)

    if (curr_close > cloud_top
            and tk_condition_long
            and cloud_proximity_long
            and chikou_ok_bull
            and future_cloud_bullish
            and adx.get("is_trending", False)
            and adx.get("trend_direction") != "BEARISH"
            and structure.get("trend") != "BEARISH"
            and vol_ctx.get("vol_ratio", 0) >= 1.2
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + cloud_thickness * 3)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["일목 5요소 LONG"]
        reasons.append(f"구름상단돌파({cloud_top:,.0f})")
        if tk_cross_bull:
            reasons.append("TK골든크로스")
        reasons.append("치코스팬확인")
        reasons.append("미래구름↑")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ctx.get('vol_ratio', 0):.1f}x")

        return Signal(
            strategy="UPBIT_ICHIMOKU",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    # 구름 하단 이탈 직후 (2% 이내) + TK 크로스 우선, tk_below는 구름 근접시만
    cloud_proximity_short = dist_from_cloud_bottom < 2.0
    tk_condition_short = tk_cross_bear or (tk_below and cloud_proximity_short)

    if (curr_close < cloud_bottom
            and tk_condition_short
            and cloud_proximity_short
            and chikou_ok_bear
            and future_cloud_bearish
            and adx.get("is_trending", False)
            and adx.get("trend_direction") != "BULLISH"
            and structure.get("trend") != "BULLISH"
            and vol_ctx.get("vol_ratio", 0) >= 1.2
            and not vol_ctx.get("is_climactic", False)):

        base_q = min(1.0, 0.5 + cloud_thickness * 3)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["일목 5요소 SHORT"]
        reasons.append(f"구름하단이탈({cloud_bottom:,.0f})")
        if tk_cross_bear:
            reasons.append("TK데드크로스")
        reasons.append("치코스팬확인")
        reasons.append("미래구름↓")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ctx.get('vol_ratio', 0):.1f}x")

        return Signal(
            strategy="UPBIT_ICHIMOKU",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Dynamic SL/TP Calculator (ATR-based)
# ---------------------------------------------------------------------------

def calc_dynamic_levels(
    df: pd.DataFrame,
    entry: float,
    side: str,
    atr_period: int = 14,
    sl_atr_mult: float = 1.5,
    tp1_atr_mult: float = 1.5,
    tp2_atr_mult: float = 2.5,
    tp3_atr_mult: float = 4.0,
    fee_pct: float = 0.001,  # Upbit 왕복 수수료 0.1% (0.05% × 2)
    sl_mode: str = "hybrid",       # "atr" | "structure" | "hybrid"
    tp_mode: str = "staged",       # "fixed" | "staged"
    key_levels: dict | None = None,
    adx: dict | None = None,
) -> tuple[float, list[float]]:
    """ATR 기반 동적 손절/목표가 계산 (v2: 시장 상태 분기).

    변동성이 큰 코인 → 넓은 SL/TP (예: DKA, 소형 알트)
    변동성이 작은 코인 → 좁은 SL/TP (예: BTC, ETH)

    sl_mode:
      - "atr": 기존 ATR × 배수
      - "structure": 구조 기반 (지지/저항선)
      - "hybrid": ATR과 구조 중 진입가에 더 가까운 것 (기본값)

    tp_mode:
      - "fixed": 기존 고정 ATR 배수
      - "staged": 시장 상태(ADX)별 단계적 배수 (기본값)

    Returns: (stop_loss, [tp1, tp2, tp3])
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    atr = talib.ATR(high, low, close, timeperiod=atr_period)
    curr_atr = float(atr[-1]) if not np.isnan(atr[-1]) else entry * 0.01

    # Clamp: minimum 0.5%, maximum 5% of entry
    min_atr = entry * 0.005
    max_atr = entry * 0.05
    curr_atr = max(min_atr, min(curr_atr, max_atr))

    fee_amount = entry * fee_pct

    lookback = min(20, len(close))
    recent_low = float(np.min(low[-lookback:]))
    recent_high = float(np.max(high[-lookback:]))

    kl = key_levels or {}

    # --- 시장 상태 감지 (ADX 기반) ---
    adx_val = adx.get("adx", 20) if adx else 20
    if adx_val > 25:
        market_state = "TRENDING"
    elif adx_val > 18:
        market_state = "WEAK_TREND"
    else:
        market_state = "RANGING"

    # --- TP 배수 결정 (tp_mode) ---
    if tp_mode == "staged":
        if market_state == "TRENDING":
            eff_tp1_mult, eff_tp2_mult, eff_tp3_mult = 2.0, 3.5, 5.0
        elif market_state == "WEAK_TREND":
            eff_tp1_mult, eff_tp2_mult, eff_tp3_mult = 1.5, 2.5, 4.0
        else:  # RANGING
            eff_tp1_mult, eff_tp2_mult, eff_tp3_mult = 1.2, 1.8, 2.5
    else:  # "fixed"
        eff_tp1_mult = tp1_atr_mult
        eff_tp2_mult = tp2_atr_mult
        eff_tp3_mult = tp3_atr_mult

    # --- SL 계산 (sl_mode) ---
    if side == "LONG":
        atr_sl = entry - curr_atr * sl_atr_mult
        atr_sl = max(atr_sl, recent_low * 0.998)
        atr_sl = min(atr_sl, entry * 0.995)

        struct_sl = 0.0
        if sl_mode in ("structure", "hybrid") and kl.get("nearest_support"):
            struct_sl = kl["nearest_support"] * 0.998

        if sl_mode == "atr" or not struct_sl:
            sl = atr_sl
        elif sl_mode == "structure":
            sl = struct_sl
        else:  # hybrid: 진입가에 더 가까운 것
            sl = max(atr_sl, struct_sl)

        # 하이브리드 거리 제한: 최소 0.5%, 최대 3%
        if sl_mode == "hybrid":
            min_sl = entry * 0.97   # 최대 3% 거리
            max_sl = entry * 0.995  # 최소 0.5% 거리
            sl = max(min_sl, min(sl, max_sl))

        sl = _tick_round(sl, "down")

        tp1 = _tick_round(entry + curr_atr * eff_tp1_mult, "up")
        tp2 = _tick_round(entry + curr_atr * eff_tp2_mult, "up")
        tp3 = _tick_round(entry + curr_atr * eff_tp3_mult, "up")

        # Enforce R:R >= 1:1 AFTER FEES
        sl_dist = entry - sl
        min_tp1 = sl_dist + 2 * fee_amount
        min_tp2 = sl_dist * 1.5 + 2 * fee_amount
        min_tp3 = sl_dist * 2.5 + 2 * fee_amount
        if tp1 - entry < min_tp1:
            tp1 = _tick_round(entry + min_tp1, "up")
        if tp2 - entry < min_tp2:
            tp2 = _tick_round(entry + min_tp2, "up")
        if tp3 - entry < min_tp3:
            tp3 = _tick_round(entry + min_tp3, "up")
    else:
        atr_sl = entry + curr_atr * sl_atr_mult
        atr_sl = min(atr_sl, recent_high * 1.002)
        atr_sl = max(atr_sl, entry * 1.005)

        struct_sl = 0.0
        if sl_mode in ("structure", "hybrid") and kl.get("nearest_resistance"):
            struct_sl = kl["nearest_resistance"] * 1.002

        if sl_mode == "atr" or not struct_sl:
            sl = atr_sl
        elif sl_mode == "structure":
            sl = struct_sl
        else:  # hybrid
            sl = min(atr_sl, struct_sl)

        # 하이브리드 거리 제한
        if sl_mode == "hybrid":
            min_sl = entry * 1.005  # 최소 0.5% 거리
            max_sl = entry * 1.03   # 최대 3% 거리
            sl = max(min_sl, min(sl, max_sl))

        sl = _tick_round(sl, "up")

        tp1 = _tick_round(entry - curr_atr * eff_tp1_mult, "down")
        tp2 = _tick_round(entry - curr_atr * eff_tp2_mult, "down")
        tp3 = _tick_round(entry - curr_atr * eff_tp3_mult, "down")

        # Enforce R:R >= 1:1 AFTER FEES
        sl_dist = sl - entry
        min_tp1 = sl_dist + 2 * fee_amount
        min_tp2 = sl_dist * 1.5 + 2 * fee_amount
        min_tp3 = sl_dist * 2.5 + 2 * fee_amount
        if entry - tp1 < min_tp1:
            tp1 = _tick_round(entry - min_tp1, "down")
        if entry - tp2 < min_tp2:
            tp2 = _tick_round(entry - min_tp2, "down")
        if entry - tp3 < min_tp3:
            tp3 = _tick_round(entry - min_tp3, "down")

    # Ensure TPs are distinct (at least 1 tick apart)
    tick = _upbit_tick(entry)
    if tp2 <= tp1:
        tp2 = tp1 + tick if side == "LONG" else tp1 - tick
    if tp3 <= tp2:
        tp3 = tp2 + tick if side == "LONG" else tp2 - tick

    return sl, [tp1, tp2, tp3]


# ---------------------------------------------------------------------------
# Signal R:R Validation — 최종 안전장치
# ---------------------------------------------------------------------------


def _inject_metadata(sig: Signal, ctx: dict) -> None:
    """시장 분석 컨텍스트를 시그널 metadata에 자동 주입."""
    from engine.analysis.confidence import get_last_breakdown

    adx = ctx.get("adx", {})
    vol = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    kl = ctx.get("key_levels", {})

    meta = {
        "trend": structure.get("trend", "—"),
        "adx": adx.get("adx", 0),
        "vol_ratio": vol.get("vol_ratio", 0),
        "obv_trend": vol.get("obv_trend", "—"),
        "is_climactic": vol.get("is_climactic", False),
        "at_support": kl.get("at_support", False),
        "at_resistance": kl.get("at_resistance", False),
        "nearest_support": kl.get("nearest_support", 0),
        "nearest_resistance": kl.get("nearest_resistance", 0),
        "support_touches": kl.get("support_touches", 0),
        "resistance_touches": kl.get("resistance_touches", 0),
        "confidence_breakdown": get_last_breakdown(),
    }

    # 역추세 판단
    trend = structure.get("trend", "RANGING")
    if (sig.side == "LONG" and trend == "BEARISH") or (sig.side == "SHORT" and trend == "BULLISH"):
        meta["counter_trend"] = True

    sig.metadata = meta


def validate_signal_rr(
    signal: Signal,
    fee_pct: float = 0.001,
) -> Signal | None:
    """시그널의 손절폭 < 익절폭 검증 (수수료 후).

    모든 전략의 최종 출력에 적용되는 안전장치.
    TP1 순이익 > SL 순손실이 아니면 시그널 폐기.
    조건 충족 시 TP 조정 후 반환, 미충족 시 None.
    """
    entry = signal.entry
    sl = signal.stop_loss
    tps = signal.take_profits

    if entry <= 0 or not tps:
        return None

    fee = entry * fee_pct  # 왕복 수수료

    if signal.side == "LONG":
        sl_dist = entry - sl           # 손절 거리 (양수)
        sl_net = sl_dist + fee         # 순손실 = 손절거리 + 수수료
    else:
        sl_dist = sl - entry
        sl_net = sl_dist + fee

    if sl_dist <= 0:
        return None  # SL이 진입가 반대편

    # 각 TP 검증: 순이익 > 순손실
    valid_tps = []
    for i, tp in enumerate(tps):
        if signal.side == "LONG":
            tp_dist = tp - entry
        else:
            tp_dist = entry - tp

        tp_net = tp_dist - fee  # 순이익

        # TP{i+1}의 최소 R:R 배수: TP1=1.0, TP2=1.5, TP3=2.5
        min_rr = [1.0, 1.5, 2.5][min(i, 2)]

        if tp_net >= sl_net * min_rr:
            valid_tps.append(tp)
        else:
            # 보정: 최소 R:R 충족하도록 TP 강제 조정
            required_dist = sl_net * min_rr + fee
            if signal.side == "LONG":
                corrected = _tick_round(entry + required_dist, "up")
            else:
                corrected = _tick_round(entry - required_dist, "down")
            valid_tps.append(corrected)

    # TP1 순이익이 여전히 SL 순손실보다 작으면 폐기
    if signal.side == "LONG":
        tp1_net = valid_tps[0] - entry - fee
    else:
        tp1_net = entry - valid_tps[0] - fee

    if tp1_net < sl_net:
        return None  # R:R 보정 불가 — 시그널 폐기

    # TP 순서 보장 (TP1 < TP2 < TP3 for LONG, 반대 for SHORT)
    tick = _upbit_tick(entry)
    for i in range(1, len(valid_tps)):
        if signal.side == "LONG" and valid_tps[i] <= valid_tps[i - 1]:
            valid_tps[i] = valid_tps[i - 1] + tick
        elif signal.side == "SHORT" and valid_tps[i] >= valid_tps[i - 1]:
            valid_tps[i] = valid_tps[i - 1] - tick

    signal.take_profits = valid_tps
    return signal


# ---------------------------------------------------------------------------
# Strategy: Early Pump Detection (급등 초입 감지)
# ---------------------------------------------------------------------------

def scan_early_pump(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """스마트머니 축적 돌파 (v2).

    LONG 조건:
    1. 3봉 거래량 증가 + 폭발 ≥ 2.5x
    2. 가격 변화 0.5-2.5%
    3. 저항선 근처가 아님
    4. BOS bullish (구조 돌파)
    5. OBV 상승 추세
    6. MFI 50-85
    7. 마지막 봉 몸통 비율 > 50%

    SHORT (미러)
    """
    cfg = config or UpbitScannerConfig()
    if len(df) < 30:
        return None

    close = df["close"].values
    vol = df["volume"].values
    opens = df["open"].values
    high = df["high"].values
    low = df["low"].values

    # Recent candles
    c1, c2, c3 = float(close[-3]), float(close[-2]), float(close[-1])
    v1, v2, v3 = float(vol[-3]), float(vol[-2]), float(vol[-1])
    o1, o2, o3 = float(opens[-3]), float(opens[-2]), float(opens[-1])

    # Volume average (20-bar)
    vol_avg = float(pd.Series(vol).rolling(20).mean().iloc[-1])
    if vol_avg <= 0:
        return None

    vol_ratio = v3 / vol_avg

    # Price change over last 3 bars
    price_3bar = (c3 - c1) / c1 * 100 if c1 > 0 else 0

    curr_close = float(close[-1])

    # Analysis context
    ctx = context or {}
    kl = ctx.get("key_levels", {})
    structure = ctx.get("structure", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    adx = ctx.get("adx", {})

    # 마지막 봉 몸통 비율
    last_range = float(high[-1]) - float(low[-1])
    last_body = abs(c3 - o3)
    body_ratio = last_body / last_range if last_range > 0 else 0

    # --- LONG (스마트머니 축적 돌파) ---
    vol_increasing = v1 < v2 < v3
    vol_explosion = vol_ratio >= 2.5
    price_early = 0.5 < price_3bar < 2.5
    bullish_streak = (c2 > o2) and (c3 > o3)

    if (vol_increasing and vol_explosion and price_early and bullish_streak
            and not kl.get("at_resistance", False)
            and structure.get("bos_bullish", False)
            and vol_ctx.get("obv_trend") == "RISING"
            and 50 < vol_ctx.get("mfi", 50) < 85
            and body_ratio > 0.5):

        base_q = min(1.0, 0.5 + (vol_ratio - 2.5) * 0.05 + price_3bar * 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"스마트머니 돌파"]
        reasons.append(f"Vol:{vol_ratio:.1f}x폭발")
        reasons.append(f"+{price_3bar:.1f}%초기")
        reasons.append("BOS↑")
        reasons.append("OBV↑")
        reasons.append(f"MFI:{vol_ctx.get('mfi', 0):.0f}")
        reasons.append(f"몸통{body_ratio:.0%}")

        return Signal(
            strategy="UPBIT_EARLY_PUMP",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT (스마트머니 분배 이탈) ---
    price_drop = -2.5 < price_3bar < -0.5
    bearish_streak = (c2 < o2) and (c3 < o3)

    if (vol_increasing and vol_explosion and price_drop and bearish_streak
            and not kl.get("at_support", False)
            and structure.get("bos_bearish", False)
            and vol_ctx.get("obv_trend") == "FALLING"
            and body_ratio > 0.5):

        base_q = min(1.0, 0.5 + (vol_ratio - 2.5) * 0.05 + abs(price_3bar) * 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"스마트머니 이탈"]
        reasons.append(f"Vol:{vol_ratio:.1f}x폭발")
        reasons.append(f"{price_3bar:.1f}%초기")
        reasons.append("BOS↓")
        reasons.append("OBV↓")
        reasons.append(f"몸통{body_ratio:.0%}")

        return Signal(
            strategy="UPBIT_EARLY_PUMP",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: SMC (Smart Money Concepts)
# ---------------------------------------------------------------------------

def scan_smc(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """스마트머니 컨셉 (SMC) 전략.

    LONG 조건:
    1. CHoCH↑ 또는 BOS↑ — 구조 전환/돌파
    2. 불리시 OB 존재 + 현재가 OB 근처 (±1.5%)
    3. FVG 불리시 보너스
    4. ADX 추세 확인
    5. 거래량 ≥ 1.2x + OBV 상승
    6. 클라이맥스 아님

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()
    if len(df) < 50:
        return None

    close = df["close"].values
    curr_close = float(close[-1])

    ctx = context or {}
    smc = ctx.get("smc", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # --- LONG ---
    choch_up = smc.get("choch_up", False)
    bos_up = smc.get("bos_up", False)
    ob_bull = smc.get("order_block_bull", 0.0)
    fvg_bull = smc.get("fvg_bull", False)

    if ((choch_up or bos_up)
            and ob_bull > 0
            and abs(curr_close - ob_bull) / curr_close < 0.015  # OB ±1.5%
            and adx.get("is_trending", False)
            and vol_ctx.get("vol_ratio", 0) >= 1.2
            and vol_ctx.get("obv_trend") == "RISING"
            and not vol_ctx.get("is_climactic", False)):

        base_q = 0.8 if choch_up else 0.6
        if fvg_bull:
            base_q = min(1.0, base_q + 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["SMC"]
        reasons.append("CHoCH↑" if choch_up else "BOS↑")
        reasons.append(f"OB:{ob_bull:,.0f}리테스트")
        if fvg_bull:
            reasons.append("FVG확인")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if vol_ctx.get("obv_trend") == "RISING":
            reasons.append("OBV↑")

        return Signal(
            strategy="UPBIT_SMC",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    choch_down = smc.get("choch_down", False)
    bos_down = smc.get("bos_down", False)
    ob_bear = smc.get("order_block_bear", 0.0)
    fvg_bear = smc.get("fvg_bear", False)

    if ((choch_down or bos_down)
            and ob_bear > 0
            and abs(curr_close - ob_bear) / curr_close < 0.015
            and adx.get("is_trending", False)
            and vol_ctx.get("vol_ratio", 0) >= 1.2
            and vol_ctx.get("obv_trend") == "FALLING"
            and not vol_ctx.get("is_climactic", False)):

        base_q = 0.8 if choch_down else 0.6
        if fvg_bear:
            base_q = min(1.0, base_q + 0.1)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = ["SMC"]
        reasons.append("CHoCH↓" if choch_down else "BOS↓")
        reasons.append(f"OB:{ob_bear:,.0f}리테스트")
        if fvg_bear:
            reasons.append("FVG확인")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        if vol_ctx.get("obv_trend") == "FALLING":
            reasons.append("OBV↓")

        return Signal(
            strategy="UPBIT_SMC",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Hidden Divergence (추세 연속)
# ---------------------------------------------------------------------------

def scan_hidden_divergence(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """히든 다이버전스 — 추세 연속 전략.

    Bullish Hidden Divergence:
    1. 가격: Higher Low (최근 저점 > 이전 저점)
    2. RSI: Lower Low (최근 RSI저점 < 이전 RSI저점)
    3. 상승 추세 내에서만
    4. OBV 상승 확인
    5. RSI 40-65
    6. ADX > 18

    Bearish Hidden Divergence (미러)
    """
    cfg = config or UpbitScannerConfig()
    if len(df) < 50:
        return None

    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    curr_close = float(close[-1])

    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    if rsi.size == 0 or np.isnan(rsi[-1]):
        return None
    curr_rsi = float(rsi[-1])

    ctx = context or {}
    structure = ctx.get("structure", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # 5-bar 피봇 저점/고점 감지 (최근 30봉)
    scan_len = min(30, len(low) - 2)
    pivot_lows = []   # (index, price, rsi_val)
    pivot_highs = []  # (index, price, rsi_val)

    for i in range(2, scan_len):
        idx = len(low) - scan_len + i
        if idx < 2 or idx >= len(low) - 2:
            continue
        # Pivot low
        if (low[idx] < low[idx - 1] and low[idx] < low[idx - 2]
                and low[idx] < low[idx + 1] and low[idx] < low[idx + 2]):
            rsi_val = float(rsi[idx]) if not np.isnan(rsi[idx]) else 50
            pivot_lows.append((idx, float(low[idx]), rsi_val))
        # Pivot high
        if (high[idx] > high[idx - 1] and high[idx] > high[idx - 2]
                and high[idx] > high[idx + 1] and high[idx] > high[idx + 2]):
            rsi_val = float(rsi[idx]) if not np.isnan(rsi[idx]) else 50
            pivot_highs.append((idx, float(high[idx]), rsi_val))

    # --- Bullish Hidden Divergence ---
    if (len(pivot_lows) >= 2
            and structure.get("trend") == "BULLISH"
            and adx.get("adx", 0) > 18
            and vol_ctx.get("obv_trend") == "RISING"
            and 40 <= curr_rsi <= 65):

        prev_pl = pivot_lows[-2]
        last_pl = pivot_lows[-1]

        # 가격 HL + RSI LL = Hidden Bullish Divergence
        if last_pl[1] > prev_pl[1] and last_pl[2] < prev_pl[2]:
            base_q = 0.7
            confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
            sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                          sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                          key_levels=kl, adx=adx)

            reasons = ["Hidden Div↑", "가격HL+RSI LL"]
            reasons.append(f"구조:BULLISH")
            reasons.append("OBV↑")
            reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
            reasons.append(f"RSI:{curr_rsi:.0f}")

            return Signal(
                strategy="UPBIT_HIDDEN_DIV",
                symbol=symbol, side="LONG", entry=curr_close,
                stop_loss=sl, take_profits=tps,
                leverage=cfg.leverage, timeframe="5m", confidence=confidence,
                reason=" | ".join(reasons),
            )

    # --- Bearish Hidden Divergence ---
    if (len(pivot_highs) >= 2
            and structure.get("trend") == "BEARISH"
            and adx.get("adx", 0) > 18
            and vol_ctx.get("obv_trend") == "FALLING"
            and 35 <= curr_rsi <= 60):

        prev_ph = pivot_highs[-2]
        last_ph = pivot_highs[-1]

        # 가격 LH + RSI HH = Hidden Bearish Divergence
        if last_ph[1] < prev_ph[1] and last_ph[2] > prev_ph[2]:
            base_q = 0.7
            confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
            sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                          sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                          key_levels=kl, adx=adx)

            reasons = ["Hidden Div↓", "가격LH+RSI HH"]
            reasons.append(f"구조:BEARISH")
            reasons.append("OBV↓")
            reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
            reasons.append(f"RSI:{curr_rsi:.0f}")

            return Signal(
                strategy="UPBIT_HIDDEN_DIV",
                symbol=symbol, side="SHORT", entry=curr_close,
                stop_loss=sl, take_profits=tps,
                leverage=cfg.leverage, timeframe="5m", confidence=confidence,
                reason=" | ".join(reasons),
            )

    return None


# ---------------------------------------------------------------------------
# Strategy: BB + RSI + StochRSI Triple Confirmation
# ---------------------------------------------------------------------------

def scan_bb_rsi_stoch(
    df: pd.DataFrame,
    symbol: str,
    config: UpbitScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """BB + RSI + StochRSI 트리플 컨펌 전략.

    LONG 조건 (3중 과매도 확인):
    1. %B < 0.15 — BB 하단 근접
    2. RSI < 35 — RSI 과매도
    3. StochRSI K < 20 + K 상승 전환
    4. 하락 추세 제외
    5. 반전 캔들 (장악형/핀바)
    6. 지지선 근처 보너스
    7. 클라이맥스 아님

    SHORT 조건 (미러)
    """
    cfg = config or UpbitScannerConfig()
    if len(df) < 30:
        return None

    close = df["close"].values
    curr_close = float(close[-1])

    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    if rsi.size == 0 or np.isnan(rsi[-1]):
        return None
    curr_rsi = float(rsi[-1])

    fastk, fastd = talib.STOCHRSI(close, timeperiod=cfg.stoch_period,
                                    fastk_period=cfg.stoch_k, fastd_period=cfg.stoch_d)
    if fastk.size == 0 or np.isnan(fastk[-1]) or np.isnan(fastd[-1]):
        return None

    curr_k = float(fastk[-1])
    prev_k = float(fastk[-2]) if not np.isnan(fastk[-2]) else curr_k

    ctx = context or {}
    bb = ctx.get("bb", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})

    pct_b = bb.get("pct_b", 0.5)

    # --- LONG (3중 과매도) ---
    has_bull_candle = candle.get("bullish_engulfing", False) or candle.get("bullish_pin_bar", False)

    if (pct_b < 0.15
            and curr_rsi < 35
            and curr_k < 20 and curr_k > prev_k  # K 상승 전환
            and structure.get("trend") != "BEARISH"
            and has_bull_candle
            and not vol_ctx.get("is_climactic", False)):

        base_q = 0.5
        if pct_b < 0.1:
            base_q += 0.1
        if curr_rsi < 30:
            base_q += 0.1
        if kl.get("at_support", False):
            base_q += 0.1
        base_q = min(0.8, base_q)

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = calc_dynamic_levels(df, curr_close, "LONG",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"BB+RSI+Stoch 과매도↑"]
        reasons.append(f"%B:{pct_b:.2f}")
        reasons.append(f"RSI:{curr_rsi:.0f}")
        reasons.append(f"StochK:{prev_k:.0f}→{curr_k:.0f}")
        if has_bull_candle:
            reasons.append("반전캔들")
        if kl.get("at_support"):
            reasons.append("지지선")

        return Signal(
            strategy="UPBIT_BB_RSI_STOCH",
            symbol=symbol, side="LONG", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT (3중 과매수) ---
    has_bear_candle = candle.get("bearish_engulfing", False) or candle.get("bearish_pin_bar", False)

    if (pct_b > 0.85
            and curr_rsi > 65
            and curr_k > 80 and curr_k < prev_k  # K 하락 전환
            and structure.get("trend") != "BULLISH"
            and has_bear_candle
            and not vol_ctx.get("is_climactic", False)):

        base_q = 0.5
        if pct_b > 0.9:
            base_q += 0.1
        if curr_rsi > 70:
            base_q += 0.1
        if kl.get("at_resistance", False):
            base_q += 0.1
        base_q = min(0.8, base_q)

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = calc_dynamic_levels(df, curr_close, "SHORT",
                                      sl_mode=cfg.sl_mode, tp_mode=cfg.tp_mode,
                                      key_levels=kl, adx=adx)

        reasons = [f"BB+RSI+Stoch 과매수↓"]
        reasons.append(f"%B:{pct_b:.2f}")
        reasons.append(f"RSI:{curr_rsi:.0f}")
        reasons.append(f"StochK:{prev_k:.0f}→{curr_k:.0f}")
        if has_bear_candle:
            reasons.append("반전캔들")
        if kl.get("at_resistance"):
            reasons.append("저항선")

        return Signal(
            strategy="UPBIT_BB_RSI_STOCH",
            symbol=symbol, side="SHORT", entry=curr_close,
            stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="5m", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy: Mega Pump Precursor (50%+ 급등 전조 감지)
# ---------------------------------------------------------------------------

# scan_mega_pump_precursor: engine/strategy/mega_pump.py 로 분리됨
from engine.strategy.mega_pump import scan_mega_pump_precursor  # noqa: F401


# ---------------------------------------------------------------------------
# Chart Generation
# ---------------------------------------------------------------------------

def _chart_style():
    """Shared dark chart style."""
    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350",
        edge={"up": "#26a69a", "down": "#ef5350"},
        wick={"up": "#26a69a", "down": "#ef5350"},
        volume={"up": "#26a69a80", "down": "#ef535080"},
    )
    return mpf.make_mpf_style(
        marketcolors=mc, base_mpf_style="nightclouds",
        gridstyle=":", gridcolor="#333333",
    )


def _draw_entry_levels(ax, signal: Signal) -> None:
    """Draw Entry / SL / TP / Support / Resistance horizontal lines and labels."""
    from matplotlib.lines import Line2D

    entry, sl, tps = signal.entry, signal.stop_loss, signal.take_profits

    ax.axhline(y=entry, color="#FFFFFF", linestyle="-", linewidth=1.5, alpha=0.9)
    ax.axhline(y=sl, color="#FF4444", linestyle="--", linewidth=1.2, alpha=0.8)

    colors_tp = ["#4CAF50", "#8BC34A", "#CDDC39"]
    labels_tp = ["TP1", "TP2", "TP3"]
    for i, tp in enumerate(tps):
        ax.axhline(y=tp, color=colors_tp[i], linestyle="--", linewidth=1.0, alpha=0.7)

    xlim = ax.get_xlim()
    ax.annotate(f"Entry {entry:,.0f}", xy=(xlim[1], entry),
                fontsize=8, color="#FFFFFF", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="#333333", alpha=0.8))
    ax.annotate(f"SL {sl:,.0f}", xy=(xlim[1], sl),
                fontsize=8, color="#FF4444", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="#331111", alpha=0.8))
    for i, tp in enumerate(tps):
        pct = abs(tp - entry) / entry * 100
        ax.annotate(f"{labels_tp[i]} {tp:,.0f} (+{pct:.1f}%)", xy=(xlim[1], tp),
                    fontsize=8, color=colors_tp[i], va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="#113311", alpha=0.8))

    # --- 지지선/저항선 (metadata에서) ---
    meta = signal.metadata if hasattr(signal, "metadata") and signal.metadata else {}
    ylim = ax.get_ylim()

    sup = meta.get("nearest_support", 0)
    res = meta.get("nearest_resistance", 0)
    sup_touches = meta.get("support_touches", 0)
    res_touches = meta.get("resistance_touches", 0)

    if sup > 0 and ylim[0] < sup < ylim[1]:
        ax.axhline(y=sup, color="#2196F3", linestyle="-.", linewidth=1.5, alpha=0.6)
        ax.axhspan(sup * 0.998, sup * 1.002, color="#2196F3", alpha=0.08)
        label = f"S {sup:,.0f}"
        if sup_touches > 0:
            label += f" ({sup_touches}회 터치)"
        ax.annotate(label, xy=(xlim[0] + (xlim[1] - xlim[0]) * 0.02, sup),
                    fontsize=7, color="#2196F3", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.15", fc="#112233", alpha=0.7))

    if res > 0 and ylim[0] < res < ylim[1]:
        ax.axhline(y=res, color="#FF9800", linestyle="-.", linewidth=1.5, alpha=0.6)
        ax.axhspan(res * 0.998, res * 1.002, color="#FF9800", alpha=0.08)
        label = f"R {res:,.0f}"
        if res_touches > 0:
            label += f" ({res_touches}회 터치)"
        ax.annotate(label, xy=(xlim[0] + (xlim[1] - xlim[0]) * 0.02, res),
                    fontsize=7, color="#FF9800", va="top",
                    bbox=dict(boxstyle="round,pad=0.15", fc="#332211", alpha=0.7))

    # --- 시장 상태 텍스트 (좌상단) ---
    trend = meta.get("trend", "")
    adx_val = meta.get("adx", 0)
    vol_ratio = meta.get("vol_ratio", 0)
    if trend or adx_val > 0:
        adx_label = "강추세" if adx_val > 25 else ("약추세" if adx_val > 18 else "횡보")
        info = f"{trend} | ADX:{adx_val:.0f}({adx_label})"
        if vol_ratio > 0:
            info += f" | Vol:{vol_ratio:.1f}x"
        counter = meta.get("counter_trend", False)
        if counter:
            info += " | ⚠역추세"
        ax.text(0.98, 0.98, info, transform=ax.transAxes,
                fontsize=7, color="#AAAAAA", ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.3", fc="#1a1a2e", ec="#444", alpha=0.85))


def _save_chart(fig) -> bytes:
    """Save figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#1a1a2e", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def generate_chart(df: pd.DataFrame, signal: Signal, config: UpbitScannerConfig | None = None) -> bytes | None:
    """Generate strategy-specific candlestick chart with indicators."""
    cfg = config or UpbitScannerConfig()

    try:
        from datetime import datetime

        # 최신 데이터 사용 (마지막 60봉)
        chart_df = df.tail(60).copy()
        chart_df.index = pd.DatetimeIndex(chart_df.index)
        close = chart_df["close"].values
        high = chart_df["high"].values
        low = chart_df["low"].values

        ticker = signal.symbol.replace("KRW-", "")
        side_label = "LONG" if signal.side == "LONG" else "SHORT"
        last_candle_time = chart_df.index[-1].strftime("%m/%d %H:%M")
        now_str = datetime.now().strftime("%m/%d %H:%M")
        style = _chart_style()
        from matplotlib.lines import Line2D

        strategy = signal.strategy

        # ---------------------------------------------------------------
        # EMA + RSI + VWAP
        # ---------------------------------------------------------------
        if strategy == "UPBIT_EMA_RSI_VWAP":
            ema_f = talib.EMA(close, timeperiod=cfg.ema_fast)
            ema_s = talib.EMA(close, timeperiod=cfg.ema_slow)
            vwap = _calc_vwap(chart_df).values
            rsi = talib.RSI(close, timeperiod=cfg.rsi_period)

            ap = [
                mpf.make_addplot(ema_f, color="#FF6B6B", width=1.2),
                mpf.make_addplot(ema_s, color="#4ECDC4", width=1.2),
                mpf.make_addplot(vwap, color="#FFD93D", width=1.0, linestyle="--"),
                mpf.make_addplot(rsi, panel=2, color="#E040FB", width=1.0, ylabel="RSI"),
                mpf.make_addplot(np.full(len(rsi), 70), panel=2, color="#FF444488", width=0.5, linestyle="--"),
                mpf.make_addplot(np.full(len(rsi), 30), panel=2, color="#4CAF5088", width=0.5, linestyle="--"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | EMA+RSI+VWAP",
                figsize=(12, 8), returnfig=True, panel_ratios=(3, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#FF6B6B", lw=1.2, label=f"EMA{cfg.ema_fast}"),
                Line2D([0], [0], color="#4ECDC4", lw=1.2, label=f"EMA{cfg.ema_slow}"),
                Line2D([0], [0], color="#FFD93D", lw=1.0, ls="--", label="VWAP"),
            ]

        # ---------------------------------------------------------------
        # Supertrend
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_SUPERTREND":
            period, mult = 10, 3.0
            atr = talib.ATR(high, low, close, timeperiod=period)
            hl2 = (high + low) / 2
            upper_band = hl2 + mult * atr
            lower_band = hl2 - mult * atr

            n = len(close)
            st_line = np.full(n, np.nan)
            direction = np.zeros(n)

            # Find first valid ATR index
            first_valid = period
            while first_valid < n and np.isnan(atr[first_valid]):
                first_valid += 1
            if first_valid >= n - 2:
                # Not enough data for Supertrend chart
                return None

            direction[first_valid] = -1
            st_line[first_valid] = upper_band[first_valid]

            for i in range(first_valid + 1, n):
                if np.isnan(upper_band[i]) or np.isnan(lower_band[i]):
                    direction[i] = direction[i - 1]
                    st_line[i] = st_line[i - 1]
                    continue

                if close[i] > upper_band[i - 1]:
                    direction[i] = 1
                elif close[i] < lower_band[i - 1]:
                    direction[i] = -1
                else:
                    direction[i] = direction[i - 1]

                prev_st = st_line[i - 1] if not np.isnan(st_line[i - 1]) else 0
                if direction[i] == 1:
                    st_line[i] = max(lower_band[i], prev_st) if direction[i - 1] == 1 else lower_band[i]
                else:
                    st_line[i] = min(upper_band[i], prev_st) if direction[i - 1] == -1 else upper_band[i]

            # Split into bullish/bearish segments for coloring
            st_bull = np.where(direction == 1, st_line, np.nan)
            st_bear = np.where(direction == -1, st_line, np.nan)

            ap = []
            if not np.all(np.isnan(st_bull)):
                ap.append(mpf.make_addplot(st_bull, color="#26a69a", width=2.0))
            if not np.all(np.isnan(st_bear)):
                ap.append(mpf.make_addplot(st_bear, color="#ef5350", width=2.0))

            # ATR subplot — replace leading NaNs with 0 for mplfinance
            atr_clean = np.nan_to_num(atr, nan=0.0)
            ap.append(mpf.make_addplot(atr_clean, panel=2, color="#FFD93D", width=1.0, ylabel="ATR"))
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | Supertrend",
                figsize=(12, 8), returnfig=True, panel_ratios=(3, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#26a69a", lw=2, label="Supertrend (Bull)"),
                Line2D([0], [0], color="#ef5350", lw=2, label="Supertrend (Bear)"),
            ]

        # ---------------------------------------------------------------
        # MACD Divergence
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_MACD_DIV":
            macd_line, signal_line, hist = talib.MACD(close, fastperiod=12,
                                                       slowperiod=26, signalperiod=9)

            # Color histogram: green if positive, red if negative
            hist_pos = np.where(hist >= 0, hist, np.nan)
            hist_neg = np.where(hist < 0, hist, np.nan)

            ap = [
                mpf.make_addplot(macd_line, panel=2, color="#2196F3", width=1.2, ylabel="MACD"),
                mpf.make_addplot(signal_line, panel=2, color="#FF9800", width=1.0),
                mpf.make_addplot(hist_pos, panel=2, type="bar", color="#26a69a", width=0.7),
                mpf.make_addplot(hist_neg, panel=2, type="bar", color="#ef5350", width=0.7),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | MACD Divergence",
                figsize=(12, 8), returnfig=True, panel_ratios=(3, 1, 1.2),
            )
            # Add divergence arrow on MACD panel
            legend = [
                Line2D([0], [0], color="#2196F3", lw=1.2, label="MACD"),
                Line2D([0], [0], color="#FF9800", lw=1.0, label="Signal"),
            ]

        # ---------------------------------------------------------------
        # Stochastic RSI
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_STOCH_RSI":
            fastk, fastd = talib.STOCHRSI(close, timeperiod=14,
                                           fastk_period=3, fastd_period=3)

            ap = [
                mpf.make_addplot(fastk, panel=2, color="#2196F3", width=1.2, ylabel="StochRSI"),
                mpf.make_addplot(fastd, panel=2, color="#FF9800", width=1.0),
                mpf.make_addplot(np.full(len(fastk), 80), panel=2, color="#FF444466", width=0.5, linestyle="--"),
                mpf.make_addplot(np.full(len(fastk), 20), panel=2, color="#4CAF5066", width=0.5, linestyle="--"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | Stochastic RSI",
                figsize=(12, 8), returnfig=True, panel_ratios=(3, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#2196F3", lw=1.2, label="StochRSI %K"),
                Line2D([0], [0], color="#FF9800", lw=1.0, label="StochRSI %D"),
            ]

        # ---------------------------------------------------------------
        # Fibonacci Retracement
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_FIBONACCI":
            # Use longer data for swing detection
            full_close = df["close"].values[-100:]
            swing_high = float(np.max(full_close))
            swing_low = float(np.min(full_close))
            diff = swing_high - swing_low

            fib_levels = {
                "0%": swing_high,
                "23.6%": swing_high - diff * 0.236,
                "38.2%": swing_high - diff * 0.382,
                "50%": swing_high - diff * 0.500,
                "61.8%": swing_high - diff * 0.618,
                "78.6%": swing_high - diff * 0.786,
                "100%": swing_low,
            }

            # Need at least one addplot for mplfinance; use a transparent EMA
            ema_f = talib.EMA(close, timeperiod=cfg.ema_fast)
            ap = [mpf.make_addplot(ema_f, color="#FFFFFF22", width=0.5)]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | Fibonacci Retracement",
                figsize=(12, 8), returnfig=True,
            )

            ax = axes[0]
            fib_colors = {
                "0%": "#FF5252", "23.6%": "#FF9800", "38.2%": "#FFD93D",
                "50%": "#FFFFFF", "61.8%": "#4CAF50", "78.6%": "#2196F3", "100%": "#9C27B0",
            }
            for label, level in fib_levels.items():
                color = fib_colors[label]
                ax.axhline(y=level, color=color, linestyle="-", linewidth=1.0, alpha=0.6)
                xlim = ax.get_xlim()
                ax.annotate(f"Fib {label} ({level:,.0f})",
                            xy=(xlim[0] + (xlim[1] - xlim[0]) * 0.02, level),
                            fontsize=7, color=color, va="bottom",
                            bbox=dict(boxstyle="round,pad=0.15", fc="#1a1a2e", alpha=0.8))

            # Shade retracement zones
            ax.axhspan(fib_levels["38.2%"], fib_levels["61.8%"],
                       alpha=0.08, color="#4CAF50", label="Golden Zone")

            legend = [
                Line2D([0], [0], color="#FFD93D", lw=1.0, label="38.2%"),
                Line2D([0], [0], color="#FFFFFF", lw=1.0, label="50%"),
                Line2D([0], [0], color="#4CAF50", lw=1.0, label="61.8% (Golden)"),
            ]

            _draw_entry_levels(ax, signal)
            ax.legend(handles=legend, loc="upper left", fontsize=8,
                      facecolor="#1a1a2e", edgecolor="#333", labelcolor="white")
            return _save_chart(fig)

        # ---------------------------------------------------------------
        # Ichimoku Cloud
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_ICHIMOKU":
            t_period, k_period, s_period = 9, 26, 52

            def midpoint(h, l, period):
                result = np.full(len(h), np.nan)
                for i in range(period - 1, len(h)):
                    result[i] = (np.max(h[i - period + 1:i + 1]) + np.min(l[i - period + 1:i + 1])) / 2
                return result

            tenkan = midpoint(high, low, t_period)
            kijun = midpoint(high, low, k_period)
            senkou_a = (tenkan + kijun) / 2
            senkou_b = midpoint(high, low, s_period)

            ap = [
                mpf.make_addplot(tenkan, color="#2196F3", width=1.0),    # 전환선 (파랑)
                mpf.make_addplot(kijun, color="#FF5252", width=1.0),     # 기준선 (빨강)
                mpf.make_addplot(senkou_a, color="#26a69a", width=0.8),  # 선행A (초록)
                mpf.make_addplot(senkou_b, color="#ef5350", width=0.8),  # 선행B (빨강)
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | Ichimoku Cloud",
                figsize=(12, 8), returnfig=True,
            )
            ax = axes[0]

            # Shade the cloud (NaN 영역은 건너뛰기 — 0으로 치환하면 y축 왜곡)
            x_range = np.arange(len(chart_df))
            valid = ~np.isnan(senkou_a) & ~np.isnan(senkou_b)
            ax.fill_between(x_range, senkou_a, senkou_b,
                            where=valid & (senkou_a >= senkou_b),
                            alpha=0.15, color="#26a69a", interpolate=True)
            ax.fill_between(x_range, senkou_a, senkou_b,
                            where=valid & (senkou_a < senkou_b),
                            alpha=0.15, color="#ef5350", interpolate=True)

            legend = [
                Line2D([0], [0], color="#2196F3", lw=1.0, label="Tenkan (9)"),
                Line2D([0], [0], color="#FF5252", lw=1.0, label="Kijun (26)"),
                Line2D([0], [0], color="#26a69a", lw=0.8, label="Senkou A"),
                Line2D([0], [0], color="#ef5350", lw=0.8, label="Senkou B"),
            ]

        # ---------------------------------------------------------------
        # Early Pump Detection (급등 초입)
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_EARLY_PUMP":
            vol = chart_df["volume"].values
            vol_avg = pd.Series(vol).rolling(20).mean().values
            vol_ratio = np.where(vol_avg > 0, vol / vol_avg, 1.0)

            # Price change rate (cumulative from first bar)
            price_change = (close - close[0]) / close[0] * 100

            ap = [
                mpf.make_addplot(vol_ratio, panel=2, color="#FF9800", width=1.2, ylabel="Vol Ratio"),
                mpf.make_addplot(np.full(len(vol_ratio), 3.0), panel=2, color="#FF444488",
                                 width=0.8, linestyle="--"),
                mpf.make_addplot(price_change, panel=3, color="#2196F3", width=1.0, ylabel="Change %"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | Early Pump Detection",
                figsize=(12, 9), returnfig=True, panel_ratios=(3, 1, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#FF9800", lw=1.2, label="Vol Ratio (vs 20-bar avg)"),
                Line2D([0], [0], color="#FF4444", lw=0.8, ls="--", label="3x Threshold"),
            ]

        # ---------------------------------------------------------------
        # Mega Pump Precursor
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_MEGA_PUMP":
            bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            ema_50 = talib.EMA(close, timeperiod=min(50, len(close) - 1))
            vol = chart_df["volume"].values
            vol_avg = pd.Series(vol).rolling(20).mean().values
            vol_ratio = np.where(vol_avg > 0, vol / vol_avg, 1.0)

            # OBV
            obv = np.zeros(len(close))
            for i in range(1, len(close)):
                if close[i] > close[i - 1]:
                    obv[i] = obv[i - 1] + vol[i]
                elif close[i] < close[i - 1]:
                    obv[i] = obv[i - 1] - vol[i]
                else:
                    obv[i] = obv[i - 1]
            # Normalize OBV for display
            obv_min, obv_max = np.min(obv), np.max(obv)
            obv_norm = (obv - obv_min) / (obv_max - obv_min) * 100 if obv_max > obv_min else obv

            ap = [
                mpf.make_addplot(bb_upper, color="#FF444466", width=0.8, linestyle="--"),
                mpf.make_addplot(bb_lower, color="#FF444466", width=0.8, linestyle="--"),
                mpf.make_addplot(bb_mid, color="#FFD93D66", width=0.6, linestyle=":"),
                mpf.make_addplot(ema_50, color="#E040FB", width=1.2),
                mpf.make_addplot(vol_ratio, panel=2, color="#FF9800", width=1.2, ylabel="Vol Ratio"),
                mpf.make_addplot(np.full(len(vol_ratio), 5.0), panel=2, color="#FF444488",
                                 width=0.8, linestyle="--"),
                mpf.make_addplot(obv_norm, panel=3, color="#00BCD4", width=1.0, ylabel="OBV"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | MEGA PUMP PRECURSOR",
                figsize=(12, 10), returnfig=True, panel_ratios=(3, 1, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#FF4444", lw=0.8, ls="--", label="BB(20,2)"),
                Line2D([0], [0], color="#E040FB", lw=1.2, label="EMA50"),
                Line2D([0], [0], color="#FF9800", lw=1.2, label="Vol Ratio"),
                Line2D([0], [0], color="#00BCD4", lw=1.0, label="OBV"),
            ]

        # ---------------------------------------------------------------
        # Tommy MACD 피크아웃
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_TOMMY_MACD":
            macd_line, signal_ln, hist = talib.MACD(
                close, fastperiod=cfg.macd_fast, slowperiod=cfg.macd_slow,
                signalperiod=cfg.macd_signal,
            )
            ap = [
                mpf.make_addplot(macd_line, panel=2, color="#26A69A", width=1.2, ylabel="MACD"),
                mpf.make_addplot(signal_ln, panel=2, color="#EF5350", width=1.0),
                mpf.make_addplot(hist, panel=2, type="bar",
                                 color="#26A69A88", width=0.7,
                                 secondary_y=False),
                mpf.make_addplot(np.zeros(len(hist)), panel=2, color="#FFFFFF44",
                                 width=0.5, linestyle="--"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | TOMMY MACD PEAKOUT",
                figsize=(12, 9), returnfig=True, panel_ratios=(3, 1, 1.5),
            )
            legend = [
                Line2D([0], [0], color="#26A69A", lw=1.2, label="MACD"),
                Line2D([0], [0], color="#EF5350", lw=1.0, label="Signal"),
                Line2D([0], [0], color="#26A69A88", lw=4, label="Histogram"),
            ]

        # ---------------------------------------------------------------
        # Tommy BB+RSI 강화
        # ---------------------------------------------------------------
        elif strategy == "UPBIT_TOMMY_BB_RSI":
            # RMA 200 based BB
            rma_period = min(200, len(close) - 1)
            rma = np.full(len(close), np.nan)
            if len(close) > rma_period:
                rma[rma_period - 1] = np.mean(close[:rma_period])
                alpha = 1.0 / rma_period
                for i in range(rma_period, len(close)):
                    rma[i] = rma[i - 1] * (1 - alpha) + close[i] * alpha
            std_vals = pd.Series(close).rolling(rma_period).std().values
            bb_up = rma + 2 * std_vals
            bb_dn = rma - 2 * std_vals
            rsi_vals = talib.RSI(close, timeperiod=cfg.rsi_period)

            ap = [
                mpf.make_addplot(bb_up, color="#AB47BC66", width=0.8, linestyle="--"),
                mpf.make_addplot(bb_dn, color="#AB47BC66", width=0.8, linestyle="--"),
                mpf.make_addplot(rma, color="#AB47BC", width=1.0, linestyle=":"),
                mpf.make_addplot(rsi_vals, panel=2, color="#FF9800", width=1.2, ylabel="RSI"),
                mpf.make_addplot(np.full(len(rsi_vals), 70), panel=2, color="#FF444488",
                                 width=0.5, linestyle="--"),
                mpf.make_addplot(np.full(len(rsi_vals), 30), panel=2, color="#4CAF5088",
                                 width=0.5, linestyle="--"),
            ]
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | TOMMY BB+RSI",
                figsize=(12, 9), returnfig=True, panel_ratios=(3, 1, 1.5),
            )
            legend = [
                Line2D([0], [0], color="#AB47BC", lw=0.8, ls="--", label="BB(RMA200,2)"),
                Line2D([0], [0], color="#FF9800", lw=1.2, label="RSI(14)"),
            ]

        # ---------------------------------------------------------------
        # Fallback (unknown strategy) — 범용 차트: EMA + BB + RSI
        # ---------------------------------------------------------------
        else:
            ema_20 = talib.EMA(close, timeperiod=min(20, len(close) - 1))
            ema_50 = talib.EMA(close, timeperiod=min(50, len(close) - 1))
            bb_up, bb_mid, bb_dn = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            rsi_vals = talib.RSI(close, timeperiod=14)

            ap = [
                mpf.make_addplot(ema_20, color="#FFD166", width=1.0),
                mpf.make_addplot(ema_50, color="#06D6A0", width=1.0),
                mpf.make_addplot(bb_up, color="#FFFFFF33", width=0.7, linestyle="--"),
                mpf.make_addplot(bb_dn, color="#FFFFFF33", width=0.7, linestyle="--"),
                mpf.make_addplot(rsi_vals, panel=2, color="#E040FB", width=1.0, ylabel="RSI"),
                mpf.make_addplot(np.full(len(rsi_vals), 70), panel=2, color="#FF444488", width=0.5, linestyle="--"),
                mpf.make_addplot(np.full(len(rsi_vals), 30), panel=2, color="#4CAF5088", width=0.5, linestyle="--"),
            ]

            # 전략 이름에서 표시명 추출
            strat_display = strategy.split(":")[0] if ":" in strategy else strategy
            fig, axes = mpf.plot(
                chart_df, type="candle", style=style, addplot=ap,
                volume=True, title=f"{ticker}/KRW {side_label} | {strat_display}",
                figsize=(12, 9), returnfig=True, panel_ratios=(3, 1, 1),
            )
            legend = [
                Line2D([0], [0], color="#FFD166", lw=1.0, label="EMA20"),
                Line2D([0], [0], color="#06D6A0", lw=1.0, label="EMA50"),
                Line2D([0], [0], color="#FFFFFF", lw=0.7, ls="--", label="BB(20,2)"),
            ]

        # Common: draw entry/SL/TP, legend, timestamp
        ax = axes[0]
        _draw_entry_levels(ax, signal)
        ax.legend(handles=legend, loc="upper left", fontsize=8,
                  facecolor="#1a1a2e", edgecolor="#333", labelcolor="white")
        # 실시간 타임스탬프 표시
        fig.text(0.99, 0.01, f"Last candle: {last_candle_time} | Generated: {now_str}",
                 ha="right", va="bottom", fontsize=7, color="#888888",
                 fontstyle="italic")
        return _save_chart(fig)

    except Exception as e:
        logger.error("Chart generation failed for %s: %s", signal.strategy, e)
        return None


# ---------------------------------------------------------------------------
# Discord Alert with Chart Image
# ---------------------------------------------------------------------------

def send_upbit_alert(signal: Signal, chart_data: bytes | None = None, webhook_url: str | None = None) -> bool:
    """Send Upbit signal alert to Discord with chart image."""
    import urllib.request
    import urllib.error

    from engine.alerts.discord import load_webhook_url

    url = webhook_url or load_webhook_url()
    if not url:
        logger.warning("Discord webhook URL not configured")
        return False

    ticker = signal.symbol.replace("KRW-", "")
    side_emoji = "\U0001f7e2" if signal.side == "LONG" else "\U0001f534"
    side_kr = "매수" if signal.side == "LONG" else "매도"

    # Strategy name mapping
    strat_names = {
        "UPBIT_EMA_RSI_VWAP": "EMA+RSI+VWAP",
        "UPBIT_SUPERTREND": "슈퍼트렌드",
        "UPBIT_MACD_DIV": "MACD 다이버전스",
        "UPBIT_STOCH_RSI": "스토캐스틱RSI",
        "UPBIT_FIBONACCI": "피보나치",
        "UPBIT_ICHIMOKU": "일목균형표",
        "UPBIT_EARLY_PUMP": "초기급등 감지",
        "UPBIT_SMC": "스마트머니",
        "UPBIT_HIDDEN_DIV": "히든 다이버전스",
        "UPBIT_BB_RSI_STOCH": "BB+RSI+Stoch",
        "UPBIT_MEGA_PUMP": "급등전조 감지",
        "UPBIT_TOMMY_MACD": "Tommy MACD 피크아웃",
        "UPBIT_TOMMY_BB_RSI": "Tommy BB+RSI 강화",
    }
    strat_display = strat_names.get(signal.strategy, signal.strategy)

    # Smart price formatting based on Upbit tick size
    def _fmt_price(p: float) -> str:
        if p >= 1000:
            return f"{p:,.0f}"
        elif p >= 100:
            return f"{p:,.1f}"
        elif p >= 10:
            return f"{p:,.2f}"
        elif p >= 1:
            return f"{p:,.3f}"
        else:
            return f"{p:,.4f}"

    # --- 메타데이터 (시장 분석 컨텍스트) ---
    meta = signal.metadata if hasattr(signal, "metadata") and signal.metadata else {}

    # 추세/구조 정보
    trend = meta.get("trend", "—")
    adx_val = meta.get("adx", 0)
    adx_label = "강한추세" if adx_val > 25 else ("약추세" if adx_val > 18 else "횡보")

    # 거래량 정보
    vol_ratio = meta.get("vol_ratio", 0)
    obv_trend = meta.get("obv_trend", "—")

    # 신뢰도 분해
    conf_breakdown = meta.get("confidence_breakdown", "")

    # --- R:R 비율 계산 ---
    sl_pct = abs(signal.stop_loss - signal.entry) / signal.entry * 100
    risk = abs(signal.entry - signal.stop_loss)

    tp_lines = []
    rr_parts = []
    for i, tp in enumerate(signal.take_profits, 1):
        tp_pct = abs(tp - signal.entry) / signal.entry * 100
        rr = abs(tp - signal.entry) / risk if risk > 0 else 0
        tp_lines.append(f"TP{i}: {_fmt_price(tp)}원 (+{tp_pct:.1f}%) `{rr:.1f}R`")
        rr_parts.append(f"{rr:.1f}R")

    rr_text = " / ".join(rr_parts) if rr_parts else "—"

    # --- 신뢰도 바 ---
    filled = int(signal.confidence * 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    conf_text = f"{bar} **{signal.confidence:.0%}**"
    if conf_breakdown:
        conf_text += f"\n`{conf_breakdown}`"

    # --- 시장 상태 라인 ---
    market_parts = []
    if trend and trend != "—":
        trend_emoji = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534", "RANGING": "\u26aa"}.get(trend, "\u26aa")
        market_parts.append(f"{trend_emoji} {trend}")
    if adx_val > 0:
        market_parts.append(f"ADX {adx_val:.0f} ({adx_label})")
    if vol_ratio > 0:
        vol_emoji = "\U0001f4c8" if vol_ratio >= 1.5 else "\U0001f4ca"
        market_parts.append(f"{vol_emoji} 거래량 {vol_ratio:.1f}x")
    if obv_trend and obv_trend != "—":
        market_parts.append(f"OBV {obv_trend}")
    market_line = " | ".join(market_parts) if market_parts else ""

    # --- 주의사항 ---
    warnings = []
    if meta.get("counter_trend", False):
        warnings.append("\u26a0\ufe0f 역추세 진입")
    if meta.get("is_climactic", False):
        warnings.append("\u26a0\ufe0f 클라이맥스 거래량")
    if meta.get("at_resistance", False) and signal.side == "LONG":
        warnings.append("\u26a0\ufe0f 저항선 근접")
    if meta.get("at_support", False) and signal.side == "SHORT":
        warnings.append("\u26a0\ufe0f 지지선 근접")
    warning_text = "\n".join(warnings) if warnings else ""

    # --- Description 구성 ---
    desc_parts = [
        f"**{strat_display}** | {side_kr} | R:R {rr_text}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"**사유**: {signal.reason}",
    ]
    if market_line:
        desc_parts.append(f"**시장**: {market_line}")
    if warning_text:
        desc_parts.append(warning_text)

    embed = {
        "title": f"{side_emoji} {signal.side} [{signal.timeframe}] — {ticker}/KRW",
        "description": "\n".join(desc_parts),
        "color": 0x26a69a if signal.side == "LONG" else 0xef5350,
        "fields": [
            {"name": "진입가", "value": f"**{_fmt_price(signal.entry)}원**", "inline": True},
            {"name": "손절가", "value": f"{_fmt_price(signal.stop_loss)}원 (-{sl_pct:.1f}%)", "inline": True},
            {"name": "신뢰도", "value": conf_text, "inline": True},
            {"name": "목표가", "value": "\n".join(tp_lines), "inline": False},
        ],
        "footer": {"text": f"Upbit KRW | {signal.timeframe} | {signal.timestamp}"},
    }

    if chart_data:
        embed["image"] = {"url": "attachment://chart.png"}

    payload_json = json.dumps({"embeds": [embed]})

    try:
        if chart_data:
            # Multipart form data for image upload
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            body = b""
            # JSON payload part
            body += f"--{boundary}\r\n".encode()
            body += b'Content-Disposition: form-data; name="payload_json"\r\n'
            body += b"Content-Type: application/json\r\n\r\n"
            body += payload_json.encode() + b"\r\n"
            # Image part
            body += f"--{boundary}\r\n".encode()
            body += b'Content-Disposition: form-data; name="files[0]"; filename="chart.png"\r\n'
            body += b"Content-Type: image/png\r\n\r\n"
            body += chart_data + b"\r\n"
            body += f"--{boundary}--\r\n".encode()

            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "TradingBot/1.0",
                },
                method="POST",
            )
        else:
            data = json.dumps({"embeds": [embed]}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json", "User-Agent": "TradingBot/1.0"},
                method="POST",
            )

        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 204)

    except Exception as e:
        logger.error("Upbit alert send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Signal Deduplication
# ---------------------------------------------------------------------------

class SignalDedup:
    """State-based signal deduplication.

    Saves full signal state per symbol. Only alerts when:
    - New symbol detected (never seen before)
    - Side changed (LONG → SHORT or vice versa)
    - Previous signal was cleared (EMA uncrossed) then re-triggered
    - Entry price moved significantly (>2% from last alerted price)

    State is persisted to disk and survives restarts.
    """

    def __init__(self) -> None:
        self._states: dict[str, dict] = {}  # symbol -> state
        self._load()

    def is_new(self, signal: Signal, timeframe: str = "5m", **_kwargs) -> bool:
        """Check if this signal represents a genuinely new trading opportunity."""
        key = f"{signal.symbol}:{signal.strategy}:{timeframe}"
        prev = self._states.get(key)

        if prev is None:
            # Never seen this symbol → new
            return True

        # Side changed (LONG → SHORT or vice versa) → new
        if prev.get("side") != signal.side:
            return True

        # Was previously cleared (no signal) and now re-triggered → new
        if prev.get("cleared", False):
            return True

        # Entry price moved significantly (>2%) from last alert → new
        prev_entry = prev.get("entry", 0)
        if prev_entry > 0:
            price_diff = abs(signal.entry - prev_entry) / prev_entry
            if price_diff > 0.02:
                return True

        # Same signal still active → duplicate
        return False

    def mark_sent(self, signal: Signal, timeframe: str = "5m") -> None:
        """Record that this signal was sent."""
        key = f"{signal.symbol}:{signal.strategy}:{timeframe}"
        self._states[key] = {
            "side": signal.side,
            "entry": signal.entry,
            "strategy": signal.strategy,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "timestamp": time.time(),
            "cleared": False,
        }
        self._save()

    def mark_cleared(self, symbol: str, strategy: str | None = None, timeframe: str = "5m") -> None:
        """Mark that a symbol no longer has an active signal.

        Called when a scan finds no signal for a previously-alerted symbol.
        Next time a signal appears, it will be treated as new.
        If strategy is None, clears all strategies for the symbol+timeframe.
        """
        if strategy:
            key = f"{symbol}:{strategy}:{timeframe}"
            if key in self._states:
                self._states[key]["cleared"] = True
        else:
            prefix = f"{symbol}:"
            suffix = f":{timeframe}"
            for key in list(self._states):
                if key.startswith(prefix) and key.endswith(suffix):
                    self._states[key]["cleared"] = True
        self._save()

    def get_state(self, symbol: str) -> dict | None:
        """Get the saved state for a symbol."""
        return self._states.get(symbol)

    def get_all_states(self) -> dict[str, dict]:
        """Get all saved states."""
        return dict(self._states)

    def _save(self) -> None:
        SENT_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Prune entries older than 24 hours
        now = time.time()
        pruned = {
            k: v for k, v in self._states.items()
            if now - v.get("timestamp", 0) < 86400
        }
        self._states = pruned
        SENT_SIGNALS_PATH.write_text(
            json.dumps(self._states, indent=2, ensure_ascii=False)
        )

    def _load(self) -> None:
        if SENT_SIGNALS_PATH.exists():
            try:
                self._states = json.loads(SENT_SIGNALS_PATH.read_text())
            except Exception:
                self._states = {}


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

def fetch_upbit_ohlcv(symbol: str, interval: str = "minute5", count: int = 200) -> pd.DataFrame | None:
    """Fetch OHLCV from Upbit."""
    try:
        df = pyupbit.get_ohlcv(symbol, interval=interval, count=count)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        logger.warning("Upbit fetch failed for %s: %s", symbol, e)
        return None


def get_upbit_krw_tickers() -> list[str]:
    """Get all KRW market tickers from Upbit."""
    try:
        tickers = pyupbit.get_tickers(fiat="KRW")
        return tickers or []
    except Exception as e:
        logger.warning("Failed to get Upbit tickers: %s", e)
        return []


def _get_active_symbols(min_volume_krw: float = 5_000_000_000) -> list[str]:
    """Get KRW tickers with 24h volume above threshold (default 50억원).

    Filters all 200+ KRW coins down to actively traded ones.
    """
    try:
        all_tickers = get_upbit_krw_tickers()
        if not all_tickers:
            return list(DEFAULT_SYMBOLS)

        # Fetch current prices to get 24h volume
        prices = pyupbit.get_current_price(all_tickers)
        if not prices:
            return list(DEFAULT_SYMBOLS)

        # Get orderbook for volume data
        active = []
        # Use ticker API for 24h acc_trade_price
        import requests
        url = "https://api.upbit.com/v1/ticker"
        # Batch in chunks of 100
        for i in range(0, len(all_tickers), 100):
            chunk = all_tickers[i:i+100]
            params = {"markets": ",".join(chunk)}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                for item in resp.json():
                    market = item["market"]
                    vol_krw = item.get("acc_trade_price_24h", 0)
                    if vol_krw >= min_volume_krw:
                        active.append((market, vol_krw))

        # Sort by volume descending
        active.sort(key=lambda x: x[1], reverse=True)
        result = [s for s, _ in active]

        logger.info("Active KRW symbols: %d / %d (vol >= %s KRW)",
                     len(result), len(all_tickers), f"{min_volume_krw:,.0f}")
        return result if result else list(DEFAULT_SYMBOLS)

    except Exception as e:
        logger.warning("Failed to get active symbols: %s", e)
        return list(DEFAULT_SYMBOLS)


# ---------------------------------------------------------------------------
# Timeframe Scan Config
# ---------------------------------------------------------------------------

@dataclass
class TimeframeScanConfig:
    """Per-timeframe scan configuration."""
    label: str              # "4h", "1h", "30m", "5m"
    upbit_interval: str     # "minute240", "minute60", "minute30", "minute5"
    cache_key: str          # "4h", "1h", "30m", "5m"
    scan_interval_sec: int  # polling interval (shorter than candle period)
    candle_buffer_sec: int  # wait after candle close
    discord_channel: str    # "tf_4h", "tf_1h", "tf_30m", "tf_5m"
    bar_count: int = 200
    # MTF higher TFs to use for trend context
    mtf_higher_tfs: list[str] = field(default_factory=list)


TIMEFRAME_CONFIGS = [
    TimeframeScanConfig(
        "4h", "minute240", "4h", 1800, 10, "tf_4h", 200,
        mtf_higher_tfs=["1d", "1w"],
    ),
    TimeframeScanConfig(
        "1h", "minute60", "1h", 600, 8, "tf_1h", 200,
        mtf_higher_tfs=["4h", "1d", "1w"],
    ),
    TimeframeScanConfig(
        "30m", "minute30", "30m", 360, 6, "tf_30m", 200,
        mtf_higher_tfs=["1h", "4h", "1d", "1w"],
    ),
    TimeframeScanConfig(
        "5m", "minute5", "5m", 60, 5, "tf_5m", 200,
        mtf_higher_tfs=["15m", "1h", "1d", "1w"],
    ),
]

# Quick lookup: label -> config
_TF_CONFIG_MAP: dict[str, TimeframeScanConfig] = {tc.label: tc for tc in TIMEFRAME_CONFIGS}


# ---------------------------------------------------------------------------
# Scanner Loop
# ---------------------------------------------------------------------------

_running = False
_task: asyncio.Task | None = None              # legacy single task (WS mode)
_tasks: dict[str, asyncio.Task] = {}           # TF label -> asyncio.Task
_config: UpbitScannerConfig | None = None
_dedup: SignalDedup | None = None
_scan_count: int = 0
_last_scan_time: str = ""
_last_symbols_count: int = 0
_alert_history: list[dict] = []
_ws_manager: UpbitWebSocketManager | None = None
_cache_manager: OHLCVCacheManager | None = None
_scan_mode: str = "polling"  # "websocket" or "polling"
_candle_close_event: asyncio.Event | None = None
_tf_scan_counts: dict[str, int] = {}           # TF label -> scan count
_tf_last_scan: dict[str, str] = {}             # TF label -> last scan time


def _build_strategy_list_internal(config: UpbitScannerConfig) -> list:
    """Build list of enabled strategy scan functions."""
    strategies = []
    if config.enable_ema_rsi_vwap:
        strategies.append(scan_ema_rsi_vwap)
    if config.enable_supertrend:
        strategies.append(scan_supertrend)
    if config.enable_macd_div:
        strategies.append(scan_macd_divergence)
    if config.enable_stoch_rsi:
        strategies.append(scan_stoch_rsi)
    if config.enable_fibonacci:
        strategies.append(scan_fibonacci)
    if config.enable_ichimoku:
        strategies.append(scan_ichimoku)
    if config.enable_early_pump:
        strategies.append(scan_early_pump)
    if config.enable_smc:
        strategies.append(scan_smc)
    if config.enable_hidden_div:
        strategies.append(scan_hidden_divergence)
    if config.enable_bb_rsi_stoch:
        strategies.append(scan_bb_rsi_stoch)
    if config.enable_mega_pump:
        strategies.append(scan_mega_pump_precursor)
    if config.enable_tommy_macd:
        from engine.strategy.tommy_macd import scan_tommy_macd
        strategies.append(scan_tommy_macd)
    if config.enable_tommy_bb_rsi:
        from engine.strategy.tommy_bb_rsi import scan_tommy_bb_rsi
        strategies.append(scan_tommy_bb_rsi)
    return strategies


async def _execute_scan_tf(symbols: list[str], tf: TimeframeScanConfig) -> int:
    """Execute a single scan pass across all symbols for a specific timeframe.

    Returns the number of new signals found.
    """
    global _scan_count, _last_scan_time, _last_symbols_count

    _scan_count += 1
    _tf_scan_counts[tf.label] = _tf_scan_counts.get(tf.label, 0) + 1
    _last_symbols_count = len(symbols)
    found = 0
    loop = asyncio.get_event_loop()

    strategies = _build_strategy_list_internal(_config)

    from engine.alerts.discord import load_webhook_url_for

    # Resolve TF-specific webhook
    webhook_url = load_webhook_url_for(tf.discord_channel)

    # --- Fetch OHLCV data ---
    if _config.parallel_fetch and _cache_manager:
        # Intervals: primary TF + MTF higher TFs
        intervals = [tf.cache_key] + [t for t in tf.mtf_higher_tfs]
        batch = await loop.run_in_executor(
            None, lambda: _cache_manager.prefetch_batch(symbols, intervals)
        )
    else:
        batch = None

    for symbol in symbols:
        try:
            # Get primary TF data
            if batch and batch.get(symbol, {}).get(tf.cache_key) is not None:
                df = batch[symbol][tf.cache_key]
            elif _cache_manager:
                df = await loop.run_in_executor(
                    None, lambda s=symbol: _cache_manager.fetch_single(s, tf.cache_key)
                )
            else:
                df = await loop.run_in_executor(
                    None, lambda s=symbol: fetch_upbit_ohlcv(s, tf.upbit_interval, tf.bar_count)
                )
            if df is None:
                continue

            # --- MTF trend context (using only higher TFs) ---
            trend_ctx = None
            if _config.enable_mtf and tf.mtf_higher_tfs:
                htfs = tf.mtf_higher_tfs
                # Map to standard analyze_mtf params: (df_15m, df_1h, df_1d, df_1w)
                def _get_htf(key):
                    if batch and batch.get(symbol, {}).get(key) is not None:
                        return batch[symbol][key]
                    if _cache_manager:
                        return _cache_manager.fetch_single(symbol, key)
                    return None

                df_15m = await loop.run_in_executor(None, lambda: _get_htf("15m")) if "15m" in htfs else None
                df_1h = await loop.run_in_executor(None, lambda: _get_htf("1h")) if "1h" in htfs else None
                df_4h = await loop.run_in_executor(None, lambda: _get_htf("4h")) if "4h" in htfs else None
                df_1d = None
                df_1w = None
                if _config.enable_daily_filter and "1d" in htfs:
                    df_1d = await loop.run_in_executor(None, lambda: _get_htf("1d"))
                if _config.enable_weekly_filter and "1w" in htfs:
                    df_1w = await loop.run_in_executor(None, lambda: _get_htf("1w"))

                # analyze_mtf expects (df_15m, df_1h, df_1d, df_1w)
                # For higher TFs, use 4h as df_1h substitute when 1h not available
                mtf_15m = df_15m if df_15m is not None else df_1h
                mtf_1h = df_1h if df_1h is not None else df_4h
                trend_ctx = analyze_mtf(mtf_15m, mtf_1h, df_1d, df_1w)

            # --- Build analysis context (1회/심볼) ---
            try:
                ctx = build_context(df)
            except Exception:
                ctx = {}

            # --- Run all enabled strategies ---
            symbol_has_signal = False
            for scan_fn in strategies:
                try:
                    sig = scan_fn(df, symbol, _config, context=ctx)
                except TypeError:
                    try:
                        sig = scan_fn(df, symbol, _config)
                    except Exception:
                        continue
                except Exception:
                    continue

                if sig is None:
                    continue

                # R:R 안전장치
                sig = validate_signal_rr(sig)
                if sig is None:
                    continue

                # 시장 분석 메타데이터 자동 주입 (모든 전략 공통)
                _inject_metadata(sig, ctx)

                symbol_has_signal = True

                # Override timeframe on signal
                sig.timeframe = tf.label

                # MTF filter
                if trend_ctx and _config.enable_mtf:
                    allowed, boost, mtf_reason = mtf_filter_signal(sig.side, trend_ctx)
                    if not allowed:
                        logger.debug("MTF blocked [%s]: %s %s %s — %s",
                                     tf.label, sig.side, symbol, sig.strategy, mtf_reason)
                        continue
                    sig.confidence = min(1.0, sig.confidence * boost)
                    sig.reason = f"{sig.reason} | {mtf_reason}"

                # State-based dedup (TF-aware)
                if not _dedup.is_new(sig, timeframe=tf.label):
                    continue

                # New signal!
                found += 1
                _dedup.mark_sent(sig, timeframe=tf.label)

                # Generate chart
                chart_data = None
                if _config and _config.send_chart:
                    chart_data = await loop.run_in_executor(
                        None, lambda d=df, s=sig: generate_chart(d, s, _config)
                    )

                # Send alert to TF-specific channel
                ok = await loop.run_in_executor(
                    None, lambda s=sig, c=chart_data, w=webhook_url: send_upbit_alert(s, c, webhook_url=w)
                )

                ticker = symbol.replace("KRW-", "")
                _alert_history.insert(0, {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "symbol": symbol,
                    "strategy": sig.strategy,
                    "side": sig.side,
                    "entry": sig.entry,
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "timeframe": tf.label,
                    "sent": ok,
                })
                if len(_alert_history) > 100:
                    _alert_history.pop()

                logger.info("Upbit signal [%s]: %s %s %s @ %s (sent=%s)",
                            tf.label, sig.side, ticker, sig.strategy, sig.entry, ok)

            if not symbol_has_signal:
                _dedup.mark_cleared(symbol, timeframe=tf.label)

        except Exception as e:
            logger.warning("Upbit scan error [%s] for %s: %s", tf.label, symbol, e)

        await asyncio.sleep(0.02 if _cache_manager else 0.1)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _last_scan_time = now_str
    _tf_last_scan[tf.label] = now_str

    if found:
        logger.info("Upbit scan [%s] #%d: %d new signals from %d symbols",
                     tf.label, _tf_scan_counts.get(tf.label, 0), found, len(symbols))

    return found


async def _execute_scan(symbols: list[str]) -> int:
    """Legacy 5m scan — delegates to _execute_scan_tf with 5m config."""
    return await _execute_scan_tf(symbols, _TF_CONFIG_MAP["5m"])


async def _get_symbols() -> list[str]:
    """Get symbols for scanning (auto-discover + manual additions).

    자동(거래량 상위) ∪ 수동(config.symbols) 합집합.
    수동 종목은 자동 목록에 없어도 항상 포함.
    """
    auto = await asyncio.get_event_loop().run_in_executor(None, _get_active_symbols)
    manual = list(_config.symbols) if _config and _config.symbols else []
    # 합집합 (순서: 자동 먼저, 수동 추가분 뒤에)
    seen = set(auto)
    merged = list(auto)
    for s in manual:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    return merged


async def _ws_event_loop() -> None:
    """WebSocket event-driven scan loop.

    5분봉 마감 이벤트를 기다렸다가 즉시 스캔 실행.
    이벤트가 없어도 5분 타임아웃으로 안전장치.
    """
    global _candle_close_event

    _candle_close_event = asyncio.Event()

    while _running:
        try:
            # Wait for candle close event or 5-minute timeout (safety net)
            try:
                await asyncio.wait_for(_candle_close_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                logger.debug("WS event timeout — running safety scan")

            _candle_close_event.clear()

            if not _running:
                break

            symbols = await _get_symbols()
            await _execute_scan(symbols)

        except Exception as e:
            logger.error("WS event loop error: %s", e)
            await asyncio.sleep(5)


async def _fallback_scan_loop() -> None:
    """Polling fallback: 5분 정각 기반 폴링.

    WebSocket 비활성화 시 사용. 5분 경계에 맞춰 스캔.
    """
    while _running:
        try:
            symbols = await _get_symbols()
            await _execute_scan(symbols)
        except Exception as e:
            logger.error("Polling scan loop error: %s", e)

        # Wait until next 5-minute boundary + 5 seconds buffer
        now = time.time()
        interval = 300  # 5 minutes
        next_boundary = (int(now // interval) + 1) * interval + 5
        wait_sec = max(5, next_boundary - time.time())
        await asyncio.sleep(wait_sec)


async def _tf_scan_loop(tf: TimeframeScanConfig) -> None:
    """Per-timeframe polling scan loop.

    Scans at tf.scan_interval_sec intervals (e.g. 5m→60s, 30m→360s).
    """
    logger.info("TF scan loop started: %s (interval=%ds)", tf.label, tf.scan_interval_sec)
    while _running:
        try:
            symbols = await _get_symbols()
            await _execute_scan_tf(symbols, tf)
        except Exception as e:
            logger.error("TF scan loop error [%s]: %s", tf.label, e)

        await asyncio.sleep(max(5, tf.scan_interval_sec))


def _on_candle_close_callback() -> None:
    """WebSocket 5분봉 마감 콜백 (asyncio event loop에서 호출)."""
    if _candle_close_event:
        _candle_close_event.set()


def _get_enabled_tf_configs(config: UpbitScannerConfig) -> list[TimeframeScanConfig]:
    """Return list of enabled TimeframeScanConfigs based on config toggles."""
    toggle_map = {
        "4h": config.enable_tf_4h,
        "1h": config.enable_tf_1h,
        "30m": config.enable_tf_30m,
        "5m": config.enable_tf_5m,
    }
    return [tc for tc in TIMEFRAME_CONFIGS if toggle_map.get(tc.label, False)]


def start() -> bool:
    """Start the Upbit scanner with multi-timeframe support."""
    global _task, _tasks, _running, _config, _dedup, _ws_manager, _cache_manager, _scan_mode

    if _running:
        return False

    _config = UpbitScannerConfig.load()
    _dedup = SignalDedup()
    _running = True

    # Initialize cache manager (more workers for multi-TF)
    if _config.parallel_fetch:
        _cache_manager = OHLCVCacheManager(max_workers=8)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    # Get enabled TF configs
    enabled_tfs = _get_enabled_tf_configs(_config)
    tf_labels = [tc.label for tc in enabled_tfs]

    # WebSocket mode applies to 5m only; other TFs always use polling
    if _config.ws_enabled:
        _scan_mode = "websocket"
        symbols = _config.symbols if _config.symbols else list(DEFAULT_SYMBOLS)
        _ws_manager = UpbitWebSocketManager(
            symbols=symbols,
            on_candle_close=_on_candle_close_callback,
        )
        _ws_manager.start(loop=loop)
        # 5m uses WS event loop if enabled
        if _config.enable_tf_5m:
            _task = loop.create_task(_ws_event_loop())
    else:
        _scan_mode = "polling"

    # Launch per-TF polling tasks (skip 5m if WS mode handles it)
    for tf_cfg in enabled_tfs:
        if tf_cfg.label == "5m" and _config.ws_enabled:
            continue  # handled by _ws_event_loop
        _tasks[tf_cfg.label] = loop.create_task(_tf_scan_loop(tf_cfg))

    logger.info("Upbit scanner started (mode=%s, TFs=%s, mtf=%s, parallel=%s)",
                 _scan_mode, tf_labels, _config.enable_mtf, _config.parallel_fetch)

    return True


def stop() -> bool:
    """Stop the Upbit scanner."""
    global _task, _tasks, _running, _ws_manager, _cache_manager, _scan_mode

    if not _running:
        return False

    _running = False

    # Signal candle close event to unblock wait
    if _candle_close_event:
        _candle_close_event.set()

    # Cancel legacy WS task
    if _task:
        _task.cancel()
        _task = None

    # Cancel all TF tasks
    for label, task in _tasks.items():
        task.cancel()
        logger.debug("Cancelled TF task: %s", label)
    _tasks.clear()

    if _ws_manager:
        _ws_manager.stop()
        _ws_manager = None

    if _cache_manager:
        _cache_manager.shutdown()
        _cache_manager = None

    _scan_mode = "polling"
    logger.info("Upbit scanner stopped")
    return True


def is_running() -> bool:
    return _running


def status() -> dict:
    # Build per-TF status
    tf_status = {}
    if _config:
        toggle_map = {
            "4h": _config.enable_tf_4h,
            "1h": _config.enable_tf_1h,
            "30m": _config.enable_tf_30m,
            "5m": _config.enable_tf_5m,
        }
        for tc in TIMEFRAME_CONFIGS:
            active = toggle_map.get(tc.label, False)
            has_task = tc.label in _tasks or (tc.label == "5m" and _task is not None)
            tf_status[tc.label] = {
                "enabled": active,
                "running": active and has_task and _running,
                "channel": tc.discord_channel,
                "scan_interval_sec": tc.scan_interval_sec,
                "scan_count": _tf_scan_counts.get(tc.label, 0),
                "last_scan": _tf_last_scan.get(tc.label, ""),
            }

    base = {
        "running": _running,
        "scan_interval_sec": _config.scan_interval_sec if _config else 30,
        "symbols_count": _last_symbols_count or len(DEFAULT_SYMBOLS),
        "scan_count": _scan_count,
        "last_scan": _last_scan_time,
        "recent_alerts": len(_alert_history),
        "mode": _scan_mode,
        "ws_status": _ws_manager.status() if _ws_manager else None,
        "cache_stats": _cache_manager.stats() if _cache_manager else None,
        "enable_mtf": _config.enable_mtf if _config else False,
        "timeframes": tf_status,
    }
    return base


def get_config() -> UpbitScannerConfig | None:
    return _config


def get_alert_history() -> list[dict]:
    return list(_alert_history)


def get_cache_manager() -> OHLCVCacheManager | None:
    return _cache_manager


def get_ws_manager() -> UpbitWebSocketManager | None:
    return _ws_manager


def analyze_symbol_mtf(symbol: str) -> dict | None:
    """특정 심볼의 MTF 분석 결과 반환 (API/Discord용)."""
    if not _cache_manager:
        # No cache — fetch directly
        df_15m = fetch_upbit_ohlcv(symbol, interval="minute15", count=100)
        df_1h = fetch_upbit_ohlcv(symbol, interval="minute60", count=50)
        df_1d = fetch_upbit_ohlcv(symbol, interval="day", count=60)
        df_1w = fetch_upbit_ohlcv(symbol, interval="week", count=26)
    else:
        df_15m = _cache_manager.fetch_single(symbol, "15m")
        df_1h = _cache_manager.fetch_single(symbol, "1h")
        df_1d = _cache_manager.fetch_single(symbol, "1d")
        df_1w = _cache_manager.fetch_single(symbol, "1w")

    ctx = analyze_mtf(df_15m, df_1h, df_1d, df_1w)
    return ctx.to_dict()


def update_config(data: dict) -> UpbitScannerConfig:
    global _config
    if _config is None:
        _config = UpbitScannerConfig.load()
    for k, v in data.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
    _config.save()
    return _config

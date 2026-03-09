"""Upbit KRW Swing Trading Scanner — 1시간봉 중기 스윙 전략.

6개 스윙 전략:
1. EMA 20/50 크로스 + 볼륨 확인
2. 이치모쿠 구름 돌파 1h
3. 수퍼트렌드(14,3.5) 방향 전환
4. MACD 다이버전스 1h
5. SMC (CHoCH/BOS/OB) 1h
6. BB 스퀴즈 브레이크아웃 + RSI

1시간 간격 자동 스캔. Discord 스윙 전용 채널로 알림.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Heavy deps (talib, numpy, pandas, matplotlib, mplfinance, engine.analysis,
# engine.strategy.upbit_scanner) are imported lazily inside functions so the
# module can be imported for config / dedup / status without them installed.

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    import talib

from engine.alerts.discord import Signal, load_webhook_url_for

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "swing_scanner.json"
SENT_SIGNALS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "swing_sent.json"

# ---------------------------------------------------------------------------
# Lazy heavy dependency loader
# ---------------------------------------------------------------------------

_deps_loaded = False


def _ensure_deps():
    """Import heavy dependencies into module globals on first use.

    Allows the module to be imported (for config/dedup/status) without
    talib, matplotlib, mplfinance, or engine.analysis installed.
    """
    global _deps_loaded, np, pd, talib
    global build_context, calc_confidence_v2, OHLCVCacheManager
    global analyze_mtf, mtf_filter_signal
    global _upbit_tick, _tick_round, calc_dynamic_levels, validate_signal_rr
    global send_upbit_alert, fetch_upbit_ohlcv, _get_active_symbols, DEFAULT_SYMBOLS

    if _deps_loaded:
        return
    import numpy as _np
    import pandas as _pd
    import talib as _talib
    np = _np  # noqa: F841
    pd = _pd  # noqa: F841
    talib = _talib  # noqa: F841

    from engine.analysis import build_context as _bc, calc_confidence_v2 as _cc
    build_context = _bc
    calc_confidence_v2 = _cc

    from engine.data.upbit_cache import OHLCVCacheManager as _CM
    OHLCVCacheManager = _CM

    from engine.strategy.upbit_mtf import analyze_mtf as _am, mtf_filter_signal as _mfs
    analyze_mtf = _am
    mtf_filter_signal = _mfs

    from engine.strategy.upbit_scanner import (
        _upbit_tick as _ut, _tick_round as _tr,
        calc_dynamic_levels as _cdl, validate_signal_rr as _vrr,
        send_upbit_alert as _sua, fetch_upbit_ohlcv as _fuo,
        _get_active_symbols as _gas, DEFAULT_SYMBOLS as _ds,
    )
    _upbit_tick = _ut
    _tick_round = _tr
    calc_dynamic_levels = _cdl
    validate_signal_rr = _vrr
    send_upbit_alert = _sua
    fetch_upbit_ohlcv = _fuo
    _get_active_symbols = _gas
    DEFAULT_SYMBOLS = _ds

    _deps_loaded = True


# ---------------------------------------------------------------------------
# Swing Scanner Config
# ---------------------------------------------------------------------------

@dataclass
class SwingScannerConfig:
    enabled: bool = True
    scan_interval_sec: int = 3600      # 1시간
    symbols: list[str] = field(default_factory=list)

    # 스윙용 지표 (5분봉 대비 넓은 파라미터)
    ema_fast: int = 20                  # vs 스캘핑 9
    ema_slow: int = 50                  # vs 스캘핑 21
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    supertrend_period: int = 14         # vs 스캘핑 10
    supertrend_multiplier: float = 3.5  # vs 스캘핑 3.0
    adx_period: int = 14
    atr_period: int = 14

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Ichimoku
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou: int = 52

    # 넓은 SL/TP (3~5% SL, 6~15% TP)
    sl_atr_mult: float = 2.0
    tp1_atr_mult: float = 3.0
    tp2_atr_mult: float = 5.0
    tp3_atr_mult: float = 8.0
    sl_mode: str = "hybrid"
    tp_mode: str = "staged"

    # 전략 토글
    enable_ema_cross: bool = True
    enable_ichimoku: bool = True
    enable_supertrend: bool = True
    enable_macd_div: bool = True
    enable_smc: bool = True
    enable_bb_squeeze: bool = True

    # 알림
    cooldown_sec: int = 3600
    discord_channel: str = "swing"
    primary_tf: str = "1h"
    enable_mtf: bool = True
    send_chart: bool = True
    leverage: int = 1
    parallel_fetch: bool = True

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> SwingScannerConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                known = {f.name for f in cls.__dataclass_fields__.values()}
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception as e:
                logger.warning("Failed to load swing scanner config: %s", e)
        return cls()


# ---------------------------------------------------------------------------
# Swing Signal Deduplication (separate from scalping)
# ---------------------------------------------------------------------------

class SwingSignalDedup:
    """State-based signal deduplication for swing signals.

    Uses a separate persistence file from the scalping dedup.
    """

    def __init__(self) -> None:
        self._states: dict[str, dict] = {}
        self._load()

    def is_new(self, signal: Signal) -> bool:
        key = f"{signal.symbol}:{signal.strategy}"
        prev = self._states.get(key)

        if prev is None:
            return True
        if prev.get("side") != signal.side:
            return True
        if prev.get("cleared", False):
            return True

        prev_entry = prev.get("entry", 0)
        if prev_entry > 0:
            price_diff = abs(signal.entry - prev_entry) / prev_entry
            if price_diff > 0.03:  # 3% for swing (vs 2% scalping)
                return True

        return False

    def mark_sent(self, signal: Signal) -> None:
        key = f"{signal.symbol}:{signal.strategy}"
        self._states[key] = {
            "side": signal.side,
            "entry": signal.entry,
            "strategy": signal.strategy,
            "confidence": signal.confidence,
            "timestamp": time.time(),
            "cleared": False,
        }
        self._save()

    def mark_cleared(self, symbol: str) -> None:
        for key in list(self._states):
            if key.startswith(f"{symbol}:"):
                self._states[key]["cleared"] = True
        self._save()

    def _save(self) -> None:
        SENT_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        pruned = {
            k: v for k, v in self._states.items()
            if now - v.get("timestamp", 0) < 172800  # 48h for swing
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
# Swing-specific SL/TP helper
# ---------------------------------------------------------------------------

def _swing_dynamic_levels(
    df,
    entry: float,
    side: str,
    config: SwingScannerConfig,
    key_levels: dict | None = None,
    adx: dict | None = None,
) -> tuple[float, list[float]]:
    """ATR-based SL/TP with swing-specific multipliers."""
    _ensure_deps()
    return calc_dynamic_levels(
        df, entry, side,
        atr_period=config.atr_period,
        sl_atr_mult=config.sl_atr_mult,
        tp1_atr_mult=config.tp1_atr_mult,
        tp2_atr_mult=config.tp2_atr_mult,
        tp3_atr_mult=config.tp3_atr_mult,
        sl_mode=config.sl_mode,
        tp_mode=config.tp_mode,
        key_levels=key_levels,
        adx=adx,
    )


# ---------------------------------------------------------------------------
# Strategy 1: EMA 20/50 Cross + Volume Confirmation
# ---------------------------------------------------------------------------

def scan_swing_ema_cross(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """EMA 20/50 크로스오버 스윙 전략.

    LONG: EMA20이 EMA50 상향 돌파 + 종가>EMA20 + RSI 40-70 + Vol≥1.5x + ADX>20
    SHORT (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    if len(df) < cfg.ema_slow + 10:
        return None

    close = df["close"].values
    ema_fast = talib.EMA(close, timeperiod=cfg.ema_fast)
    ema_slow = talib.EMA(close, timeperiod=cfg.ema_slow)
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)

    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0

    curr_close = float(close[-1])
    curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50.0

    ctx = context or {}
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # EMA cross detection
    curr_fast = float(ema_fast[-1])
    prev_fast = float(ema_fast[-2])
    curr_slow = float(ema_slow[-1])
    prev_slow = float(ema_slow[-2])

    if np.isnan(prev_fast) or np.isnan(prev_slow):
        return None

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    # --- LONG ---
    if (golden_cross
            and curr_close > curr_fast
            and 40 < curr_rsi < 70
            and vol_ratio >= 1.5
            and adx.get("adx", 0) > 20):

        base_q = min(1.0, 0.55 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = ["EMA20/50 골든크로스"]
        if structure.get("trend") == "BULLISH":
            reasons.append("구조:BULLISH")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="SWING_EMA_CROSS", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    if (death_cross
            and curr_close < curr_fast
            and 30 < curr_rsi < 60
            and vol_ratio >= 1.5
            and adx.get("adx", 0) > 20):

        base_q = min(1.0, 0.55 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = ["EMA20/50 데드크로스"]
        if structure.get("trend") == "BEARISH":
            reasons.append("구조:BEARISH")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="SWING_EMA_CROSS", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy 2: Ichimoku Cloud Breakout
# ---------------------------------------------------------------------------

def scan_swing_ichimoku(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """이치모쿠 구름 돌파 스윙 전략.

    LONG: 종가 구름 상향 돌파 + 전환선>기준선 + Vol≥1.3x
    SHORT (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    required = cfg.ichimoku_senkou + cfg.ichimoku_kijun + 5
    if len(df) < required:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    # Ichimoku components
    tenkan_high = pd.Series(high).rolling(cfg.ichimoku_tenkan).max().values
    tenkan_low = pd.Series(low).rolling(cfg.ichimoku_tenkan).min().values
    tenkan = (tenkan_high + tenkan_low) / 2

    kijun_high = pd.Series(high).rolling(cfg.ichimoku_kijun).max().values
    kijun_low = pd.Series(low).rolling(cfg.ichimoku_kijun).min().values
    kijun = (kijun_high + kijun_low) / 2

    senkou_a = (tenkan + kijun) / 2
    senkou_b_high = pd.Series(high).rolling(cfg.ichimoku_senkou).max().values
    senkou_b_low = pd.Series(low).rolling(cfg.ichimoku_senkou).min().values
    senkou_b = (senkou_b_high + senkou_b_low) / 2

    curr_close = float(close[-1])
    prev_close = float(close[-2])
    curr_tenkan = float(tenkan[-1])
    curr_kijun = float(kijun[-1])

    cloud_top = max(float(senkou_a[-1]), float(senkou_b[-1]))
    cloud_bottom = min(float(senkou_a[-1]), float(senkou_b[-1]))
    prev_cloud_top = max(float(senkou_a[-2]), float(senkou_b[-2]))
    prev_cloud_bottom = min(float(senkou_a[-2]), float(senkou_b[-2]))

    if any(np.isnan(x) for x in [curr_tenkan, curr_kijun, cloud_top, cloud_bottom]):
        return None

    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0

    ctx = context or {}
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # --- LONG: cloud breakout ---
    if (curr_close > cloud_top
            and prev_close <= prev_cloud_top
            and curr_tenkan > curr_kijun
            and vol_ratio >= 1.3):

        base_q = min(1.0, 0.6 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = ["이치모쿠 구름 상향돌파"]
        reasons.append(f"전환선>기준선")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_ICHIMOKU", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT: cloud breakdown ---
    if (curr_close < cloud_bottom
            and prev_close >= prev_cloud_bottom
            and curr_tenkan < curr_kijun
            and vol_ratio >= 1.3):

        base_q = min(1.0, 0.6 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = ["이치모쿠 구름 하향돌파"]
        reasons.append(f"전환선<기준선")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_ICHIMOKU", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy 3: Supertrend Direction Change
# ---------------------------------------------------------------------------

def scan_swing_supertrend(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """수퍼트렌드(14,3.5) 방향 전환 스윙 전략.

    LONG: 방향 -1→+1 전환 + 구조≠BEARISH + ADX>18 + Vol≥1.2x
    SHORT (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    period = cfg.supertrend_period
    multiplier = cfg.supertrend_multiplier
    if len(df) < period + 20:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    atr = talib.ATR(high, low, close, timeperiod=period)
    hl2 = (high + low) / 2

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    n = len(close)
    supertrend = np.zeros(n)
    direction = np.zeros(n)

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

    curr_dir = direction[-1]
    prev_dir = direction[-2]
    curr_close = float(close[-1])

    ctx = context or {}
    structure = ctx.get("structure", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0
    atr_pct = float(atr[-1]) / curr_close * 100 if curr_close > 0 else 0

    # --- LONG ---
    if (prev_dir == -1 and curr_dir == 1
            and structure.get("trend") != "BEARISH"
            and adx.get("adx", 0) > 18
            and vol_ratio >= 1.2):

        base_q = min(1.0, 0.5 + atr_pct * 1.5)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = ["Supertrend 전환↑ (1h)"]
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_SUPERTREND", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    if (prev_dir == 1 and curr_dir == -1
            and structure.get("trend") != "BULLISH"
            and adx.get("adx", 0) > 18
            and vol_ratio >= 1.2):

        base_q = min(1.0, 0.5 + atr_pct * 1.5)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = ["Supertrend 전환↓ (1h)"]
        reasons.append(f"구조:{structure.get('trend', '?')}")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_SUPERTREND", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy 4: MACD Divergence
# ---------------------------------------------------------------------------

def scan_swing_macd_div(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """MACD 다이버전스 스윙 전략 (1h).

    Bullish: 가격 Lower Low + MACD Higher Low + 히스토그램 양전환 + RSI<45
    Bearish (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    lookback = 30
    if len(df) < cfg.macd_slow + lookback:
        return None

    close = df["close"].values
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)
    macd_line, signal_line, hist = talib.MACD(
        close, fastperiod=cfg.macd_fast,
        slowperiod=cfg.macd_slow,
        signalperiod=cfg.macd_signal,
    )

    curr_close = float(close[-1])
    curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50.0
    recent_close = close[-lookback:]
    recent_macd = macd_line[-lookback:]

    if np.isnan(recent_macd).any():
        return None

    ctx = context or {}
    kl = ctx.get("key_levels", {})
    candle = ctx.get("candle", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})

    half = lookback // 2
    early_close = recent_close[:half]
    late_close = recent_close[half:]

    early_price_min = float(np.min(early_close))
    late_price_min = float(np.min(late_close))
    early_macd_min = float(np.min(recent_macd[:half]))
    late_macd_min = float(np.min(recent_macd[half:]))

    early_price_max = float(np.max(early_close))
    late_price_max = float(np.max(late_close))
    early_macd_max = float(np.max(recent_macd[:half]))
    late_macd_max = float(np.max(recent_macd[half:]))

    hist_turning_up = float(hist[-1]) > float(hist[-2]) and float(hist[-2]) > float(hist[-3])
    hist_turning_down = float(hist[-1]) < float(hist[-2]) and float(hist[-2]) < float(hist[-3])
    hist_cross_zero_up = float(hist[-1]) > 0 and float(hist[-2]) <= 0
    hist_cross_zero_down = float(hist[-1]) < 0 and float(hist[-2]) >= 0

    base_q = min(1.0, 0.55 + abs(float(hist[-1])) / curr_close * 500)

    # --- Bullish divergence ---
    if (late_price_min < early_price_min
            and late_macd_min > early_macd_min
            and (hist_turning_up or hist_cross_zero_up)
            and curr_rsi < 45):

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = ["MACD 상승 다이버전스 (1h)"]
        if kl.get("at_support"):
            reasons.append("지지선확인")
        if candle.get("bullish_engulfing"):
            reasons.append("장악형캔들")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="SWING_MACD_DIV", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- Bearish divergence ---
    if (late_price_max > early_price_max
            and late_macd_max < early_macd_max
            and (hist_turning_down or hist_cross_zero_down)
            and curr_rsi > 55):

        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = ["MACD 하락 다이버전스 (1h)"]
        if kl.get("at_resistance"):
            reasons.append("저항선확인")
        if candle.get("bearish_engulfing"):
            reasons.append("장악형캔들")
        reasons.append(f"RSI:{curr_rsi:.0f}")

        return Signal(
            strategy="SWING_MACD_DIV", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy 5: SMC (CHoCH/BOS/OB)
# ---------------------------------------------------------------------------

def scan_swing_smc(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """SMC 스윙 전략 (1h) — CHoCH/BOS + Order Block.

    LONG: CHoCH/BOS Bullish + Bull OB + Vol≥1.2x + ADX>15
    SHORT (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    if len(df) < 50:
        return None

    ctx = context or {}
    smc = ctx.get("smc", {})
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    if not smc:
        return None

    curr_close = float(df["close"].values[-1])
    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0

    choch_bull = smc.get("choch_bullish", False)
    choch_bear = smc.get("choch_bearish", False)
    bos_bull = smc.get("bos_bullish", False)
    bos_bear = smc.get("bos_bearish", False)
    has_bull_ob = smc.get("bullish_ob", False)
    has_bear_ob = smc.get("bearish_ob", False)

    # --- LONG ---
    if ((choch_bull or bos_bull)
            and has_bull_ob
            and vol_ratio >= 1.2
            and adx.get("adx", 0) > 15):

        base_q = min(1.0, 0.6 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = []
        if choch_bull:
            reasons.append("CHoCH Bullish (1h)")
        if bos_bull:
            reasons.append("BOS Bullish")
        reasons.append("Bull OB")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_SMC", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT ---
    if ((choch_bear or bos_bear)
            and has_bear_ob
            and vol_ratio >= 1.2
            and adx.get("adx", 0) > 15):

        base_q = min(1.0, 0.6 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = []
        if choch_bear:
            reasons.append("CHoCH Bearish (1h)")
        if bos_bear:
            reasons.append("BOS Bearish")
        reasons.append("Bear OB")
        reasons.append(f"ADX:{adx.get('adx', 0):.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_SMC", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Strategy 6: BB Squeeze Breakout + RSI
# ---------------------------------------------------------------------------

def scan_swing_bb_squeeze(
    df: pd.DataFrame,
    symbol: str,
    config: SwingScannerConfig | None = None,
    context: dict | None = None,
) -> Signal | None:
    """볼린저밴드 스퀴즈 브레이크아웃 스윙 전략 (1h).

    스퀴즈 = BB 폭이 최근 20봉 중 최소 부근.
    LONG: BB 상단 돌파 + RSI>50 + Vol≥1.5x
    SHORT (미러)
    """
    _ensure_deps()
    cfg = config or SwingScannerConfig()
    if len(df) < cfg.bb_period + 20:
        return None

    close = df["close"].values
    upper, middle, lower = talib.BBANDS(
        close, timeperiod=cfg.bb_period, nbdevup=cfg.bb_std, nbdevdn=cfg.bb_std,
    )
    rsi = talib.RSI(close, timeperiod=cfg.rsi_period)

    if np.isnan(upper[-1]) or np.isnan(lower[-1]):
        return None

    curr_close = float(close[-1])
    prev_close = float(close[-2])
    curr_upper = float(upper[-1])
    curr_lower = float(lower[-1])
    curr_middle = float(middle[-1])
    curr_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else 50.0

    # BB width (squeeze detection)
    bb_width = (upper - lower) / middle
    bb_width_series = bb_width[-20:]
    if np.isnan(bb_width_series).all():
        return None
    curr_width = float(bb_width[-1])
    min_width = float(np.nanmin(bb_width_series))
    is_squeeze = curr_width <= min_width * 1.1

    vol = df["volume"].values
    vol_avg = pd.Series(vol).rolling(20).mean().values
    vol_ratio = vol[-1] / vol_avg[-1] if vol_avg[-1] > 0 else 0

    ctx = context or {}
    adx = ctx.get("adx", {})
    vol_ctx = ctx.get("volume", {})
    structure = ctx.get("structure", {})
    candle = ctx.get("candle", {})
    kl = ctx.get("key_levels", {})

    # --- LONG: upper band breakout after squeeze ---
    if (is_squeeze
            and curr_close > curr_upper
            and prev_close <= float(upper[-2])
            and curr_rsi > 50
            and vol_ratio >= 1.5):

        base_q = min(1.0, 0.55 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "LONG")
        sl, tps = _swing_dynamic_levels(df, curr_close, "LONG", cfg, kl, adx)

        reasons = ["BB 스퀴즈 상향돌파 (1h)"]
        reasons.append(f"BB폭:{curr_width:.4f}")
        reasons.append(f"RSI:{curr_rsi:.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_BB_SQUEEZE", symbol=symbol, side="LONG",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    # --- SHORT: lower band breakout after squeeze ---
    if (is_squeeze
            and curr_close < curr_lower
            and prev_close >= float(lower[-2])
            and curr_rsi < 50
            and vol_ratio >= 1.5):

        base_q = min(1.0, 0.55 + (vol_ratio - 1) * 0.15)
        confidence = calc_confidence_v2(base_q, adx, vol_ctx, structure, candle, kl, "SHORT")
        sl, tps = _swing_dynamic_levels(df, curr_close, "SHORT", cfg, kl, adx)

        reasons = ["BB 스퀴즈 하향돌파 (1h)"]
        reasons.append(f"BB폭:{curr_width:.4f}")
        reasons.append(f"RSI:{curr_rsi:.0f}")
        reasons.append(f"Vol:{vol_ratio:.1f}x")

        return Signal(
            strategy="SWING_BB_SQUEEZE", symbol=symbol, side="SHORT",
            entry=curr_close, stop_loss=sl, take_profits=tps,
            leverage=cfg.leverage, timeframe="1h", confidence=confidence,
            reason=" | ".join(reasons),
        )

    return None


# ---------------------------------------------------------------------------
# Chart Generation (simplified for swing)
# ---------------------------------------------------------------------------

def generate_swing_chart(
    df: pd.DataFrame,
    signal: Signal,
    config: SwingScannerConfig | None = None,
) -> bytes | None:
    """Generate 1h swing trading chart with EMA overlay + entry levels."""
    _ensure_deps()
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import mplfinance as mpf

        cfg = config or SwingScannerConfig()
        plot_df = df.tail(60).copy()
        if len(plot_df) < 10:
            return None

        if not isinstance(plot_df.index, pd.DatetimeIndex):
            plot_df.index = pd.to_datetime(plot_df.index)

        close = plot_df["close"].values
        ema_fast = talib.EMA(close, timeperiod=cfg.ema_fast)
        ema_slow = talib.EMA(close, timeperiod=cfg.ema_slow)

        addplots = []

        ema_f_series = pd.Series(ema_fast, index=plot_df.index)
        ema_s_series = pd.Series(ema_slow, index=plot_df.index)
        addplots.append(mpf.make_addplot(ema_f_series, color="#FF9800", width=1.2))
        addplots.append(mpf.make_addplot(ema_s_series, color="#2196F3", width=1.2))

        # Entry/SL/TP horizontal lines
        n = len(plot_df)
        entry_line = pd.Series([signal.entry] * n, index=plot_df.index)
        sl_line = pd.Series([signal.stop_loss] * n, index=plot_df.index)
        addplots.append(mpf.make_addplot(entry_line, color="white", linestyle="--", width=0.8))
        addplots.append(mpf.make_addplot(sl_line, color="#F44336", linestyle="--", width=0.8))

        tp_colors = ["#4CAF50", "#8BC34A", "#CDDC39"]
        for i, tp in enumerate(signal.take_profits[:3]):
            tp_line = pd.Series([tp] * n, index=plot_df.index)
            addplots.append(mpf.make_addplot(
                tp_line, color=tp_colors[min(i, 2)], linestyle="--", width=0.8,
            ))

        mc = mpf.make_marketcolors(
            up="#26a69a", down="#ef5350",
            edge="inherit", wick="inherit",
            volume={"up": "#26a69a80", "down": "#ef535080"},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc, base_mpf_style="nightclouds",
            facecolor="#1a1a2e", figcolor="#1a1a2e",
            gridcolor="#333355", gridstyle="--",
        )

        ticker = signal.symbol.replace("KRW-", "")
        side_kr = "매수" if signal.side == "LONG" else "매도"

        fig, axes = mpf.plot(
            plot_df, type="candle", style=style,
            addplot=addplots, volume=True,
            title=f"\n{ticker}/KRW 1H — {signal.strategy} {side_kr}",
            figsize=(12, 7), returnfig=True,
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                    facecolor="#1a1a2e", edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning("Swing chart generation failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Scanner Loop
# ---------------------------------------------------------------------------

_running = False
_task: asyncio.Task | None = None
_config: SwingScannerConfig | None = None
_dedup: SwingSignalDedup | None = None
_scan_count: int = 0
_last_scan_time: str = ""
_last_symbols_count: int = 0
_alert_history: list[dict] = []
_cache_manager: OHLCVCacheManager | None = None


def _build_swing_strategy_list(config: SwingScannerConfig) -> list:
    """Build list of enabled swing strategy scan functions."""
    strategies = []
    if config.enable_ema_cross:
        strategies.append(scan_swing_ema_cross)
    if config.enable_ichimoku:
        strategies.append(scan_swing_ichimoku)
    if config.enable_supertrend:
        strategies.append(scan_swing_supertrend)
    if config.enable_macd_div:
        strategies.append(scan_swing_macd_div)
    if config.enable_smc:
        strategies.append(scan_swing_smc)
    if config.enable_bb_squeeze:
        strategies.append(scan_swing_bb_squeeze)
    return strategies


async def _execute_swing_scan(symbols: list[str]) -> int:
    """Execute a single swing scan pass across all symbols."""
    global _scan_count, _last_scan_time, _last_symbols_count

    _scan_count += 1
    _last_symbols_count = len(symbols)
    found = 0
    loop = asyncio.get_event_loop()

    strategies = _build_swing_strategy_list(_config)
    webhook_url = load_webhook_url_for(_config.discord_channel)

    # Fetch OHLCV data
    if _config.parallel_fetch and _cache_manager:
        intervals = ["1h"]
        if _config.enable_mtf:
            intervals.extend(["1d", "1w"])
        batch = await loop.run_in_executor(
            None, lambda: _cache_manager.prefetch_batch(symbols, intervals)
        )
    else:
        batch = None

    for symbol in symbols:
        try:
            # Get 1h data (primary)
            if batch and batch.get(symbol, {}).get("1h") is not None:
                df = batch[symbol]["1h"]
            elif _cache_manager:
                df = await loop.run_in_executor(
                    None, lambda s=symbol: _cache_manager.fetch_single(s, "1h")
                )
            else:
                df = await loop.run_in_executor(
                    None, lambda s=symbol: fetch_upbit_ohlcv(s, interval="minute60", count=200)
                )
            if df is None:
                continue

            # MTF context (1d, 1w for swing)
            trend_ctx = None
            if _config.enable_mtf:
                df_1d = None
                df_1w = None
                if batch:
                    df_1d = batch[symbol].get("1d")
                    df_1w = batch[symbol].get("1w")
                if df_1d is None and _cache_manager:
                    df_1d = await loop.run_in_executor(
                        None, lambda s=symbol: _cache_manager.fetch_single(s, "1d")
                    )
                if df_1w is None and _cache_manager:
                    df_1w = await loop.run_in_executor(
                        None, lambda s=symbol: _cache_manager.fetch_single(s, "1w")
                    )
                trend_ctx = analyze_mtf(None, df, df_1d, df_1w)

            # Build analysis context
            try:
                ctx = build_context(df)
            except Exception:
                ctx = {}

            # Run all enabled swing strategies
            symbol_has_signal = False
            for scan_fn in strategies:
                try:
                    sig = scan_fn(df, symbol, _config, context=ctx)
                except Exception:
                    continue

                if sig is None:
                    continue

                sig = validate_signal_rr(sig)
                if sig is None:
                    continue

                symbol_has_signal = True

                # MTF filter
                if trend_ctx and _config.enable_mtf:
                    allowed, boost, mtf_reason = mtf_filter_signal(sig.side, trend_ctx)
                    if not allowed:
                        logger.debug("MTF blocked swing: %s %s %s — %s",
                                     sig.side, symbol, sig.strategy, mtf_reason)
                        continue
                    sig.confidence = min(1.0, sig.confidence * boost)
                    sig.reason = f"{sig.reason} | {mtf_reason}"

                # Dedup
                if not _dedup.is_new(sig):
                    continue

                found += 1
                _dedup.mark_sent(sig)

                # Generate chart
                chart_data = None
                if _config.send_chart:
                    chart_data = await loop.run_in_executor(
                        None, lambda d=df, s=sig: generate_swing_chart(d, s, _config)
                    )

                # Send alert to swing channel
                ok = await loop.run_in_executor(
                    None, lambda s=sig, c=chart_data, w=webhook_url: send_upbit_alert(s, c, webhook_url=w)
                )

                _alert_history.insert(0, {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "symbol": symbol,
                    "strategy": sig.strategy,
                    "side": sig.side,
                    "entry": sig.entry,
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "sent": ok,
                })
                if len(_alert_history) > 100:
                    _alert_history.pop()

                logger.info("Swing signal: %s %s %s @ %s (sent=%s)",
                            sig.side, symbol.replace("KRW-", ""), sig.strategy, sig.entry, ok)

            if not symbol_has_signal:
                _dedup.mark_cleared(symbol)

        except Exception as e:
            logger.warning("Swing scan error for %s: %s", symbol, e)

        await asyncio.sleep(0.02 if _cache_manager else 0.1)

    _last_scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if found:
        logger.info("Swing scan #%d: %d new signals from %d symbols",
                     _scan_count, found, len(symbols))

    return found


async def _swing_scan_loop() -> None:
    """1시간 간격 스윙 스캔 루프.

    정시 + 10초에 스캔 실행 (봉 마감 대기).
    """
    while _running:
        try:
            symbols = await _get_swing_symbols()
            await _execute_swing_scan(symbols)
        except Exception as e:
            logger.error("Swing scan loop error: %s", e)

        # Next hour boundary + 10 seconds
        now = time.time()
        interval = _config.scan_interval_sec if _config else 3600
        next_boundary = (int(now // interval) + 1) * interval + 10
        wait_sec = max(10, next_boundary - time.time())
        await asyncio.sleep(wait_sec)


async def _get_swing_symbols() -> list[str]:
    """Get symbols for swing scanning."""
    auto = await asyncio.get_event_loop().run_in_executor(None, _get_active_symbols)
    manual = list(_config.symbols) if _config and _config.symbols else []
    seen = set(auto)
    merged = list(auto)
    for s in manual:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start() -> bool:
    """Start the swing scanner."""
    global _task, _running, _config, _dedup, _cache_manager

    if _running:
        return False

    _ensure_deps()
    _config = SwingScannerConfig.load()
    _dedup = SwingSignalDedup()
    _running = True

    if _config.parallel_fetch:
        _cache_manager = OHLCVCacheManager(max_workers=3)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    _task = loop.create_task(_swing_scan_loop())
    logger.info("Swing scanner started (interval=%ds, mtf=%s)",
                 _config.scan_interval_sec, _config.enable_mtf)
    return True


def stop() -> bool:
    """Stop the swing scanner."""
    global _task, _running, _cache_manager

    if not _running:
        return False

    _running = False

    if _task:
        _task.cancel()
        _task = None

    if _cache_manager:
        _cache_manager.shutdown()
        _cache_manager = None

    logger.info("Swing scanner stopped")
    return True


def is_running() -> bool:
    return _running


def status() -> dict:
    return {
        "running": _running,
        "scan_interval_sec": _config.scan_interval_sec if _config else 3600,
        "symbols_count": _last_symbols_count or 20,
        "scan_count": _scan_count,
        "last_scan": _last_scan_time,
        "recent_alerts": len(_alert_history),
        "mode": "polling",
        "enable_mtf": _config.enable_mtf if _config else True,
        "discord_channel": _config.discord_channel if _config else "swing",
    }


def get_config() -> SwingScannerConfig | None:
    return _config


def get_alert_history() -> list[dict]:
    return list(_alert_history)


def update_config(data: dict) -> SwingScannerConfig:
    global _config
    if _config is None:
        _config = SwingScannerConfig.load()
    for k, v in data.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
    _config.save()
    return _config

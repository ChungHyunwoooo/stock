"""Signal scanner — runs all strategies against live data and dispatches alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from engine.alerts.discord import Signal, send_signal
from engine.data.provider_crypto import CryptoProvider
from engine.indicators.custom import watermelon_indicator, staircase_indicator
from engine.strategy.scalping import scan_volume_spike, scan_rsi_extreme
from engine.strategy.momentum import scan_momentum
from engine.strategy.funding import scan_funding_rate, fetch_funding_rates
from engine.strategy.daytrading import scan_ema_cross, scan_bb_squeeze, scan_key_level_break, scan_candle_surge

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    signals: list[Signal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned_at: str = ""

    def __post_init__(self) -> None:
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Per-strategy scan functions (daily timeframe)
# ---------------------------------------------------------------------------

def _scan_watermelon_breakout(
    df: pd.DataFrame, symbol: str, regime: str,
) -> Signal | None:
    """S1: Watermelon Breakout — 수박 충진 80%+ 후 계단 돌파."""
    if len(df) < 450:
        return None

    wm = watermelon_indicator(df)
    sc = staircase_indicator(df)

    shell = float(wm["shell"].iloc[-1])
    melon = float(wm["melon"].iloc[-1])
    staircase = float(sc["staircase"].iloc[-1])

    if shell <= 0:
        return None

    fill = melon / shell * 100 if shell > 0 else 0
    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])

    if fill >= 80 and prev_close <= staircase and close > staircase:
        import talib
        atr = float(talib.ATR(df["high"].values, df["low"].values, df["close"].values, 14)[-1])
        sl = round(staircase - atr * 1.5, 6)
        risk = close - sl
        sig = Signal(
            strategy="S1_WATERMELON_BREAKOUT",
            symbol=symbol,
            side="LONG",
            entry=round(close, 6),
            stop_loss=sl,
            take_profits=[round(close + risk * 2, 6), round(close + risk * 3, 6)],
            leverage=4,
            timeframe="1d",
            confidence=min(1.0, fill / 100),
            reason=f"수박 충진 {fill:.0f}% + 세력계단 ${staircase:,.2f} 돌파",
        )
        # Apply regime confidence weighting instead of hard block
        if regime == "BEAR_MARKET":
            sig.confidence *= 0.5
        elif regime == "ALT_SEASON":
            sig.confidence = min(1.0, sig.confidence * 1.2)
        return sig
    return None


def _scan_staircase_bounce(
    df: pd.DataFrame, symbol: str, regime: str,
) -> Signal | None:
    """S2: Staircase Bounce — 세력계단 근접 + 양봉 확인."""
    if len(df) < 450:
        return None

    sc = staircase_indicator(df)
    prox1 = float(sc["proximity1"].iloc[-1]) > 0
    prox2 = float(sc["proximity2"].iloc[-1]) > 0

    if not (prox1 or prox2):
        return None

    last = df.iloc[-1]
    close = float(last["close"])
    is_bullish = last["close"] > last["open"]

    if not is_bullish:
        return None

    staircase = float(sc["staircase"].iloc[-1])
    import talib
    atr = float(talib.ATR(df["high"].values, df["low"].values, df["close"].values, 14)[-1])
    sl = round(staircase - atr, 6)
    ema112 = float(df["close"].ewm(span=112, adjust=False).mean().iloc[-1])

    signal_type = "근접2 (매수시작)" if prox2 else "근접1 (매수준비)"
    sig = Signal(
        strategy="S2_STAIRCASE_BOUNCE",
        symbol=symbol,
        side="LONG",
        entry=round(close, 6),
        stop_loss=sl,
        take_profits=[round(ema112, 6)],
        leverage=3 if prox2 else 2,
        timeframe="1d",
        confidence=0.7 if prox2 else 0.5,
        reason=f"{signal_type} 활성 + 양봉 확인. 계단 ${staircase:,.2f}",
    )
    # Apply regime confidence weighting instead of hard block
    if regime == "BEAR_MARKET":
        sig.confidence *= 0.5
    elif regime == "ALT_SEASON":
        sig.confidence = min(1.0, sig.confidence * 1.2)
    return sig


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

WATCH_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT",
    "ADA/USDT", "DOT/USDT", "MATIC/USDT", "ARB/USDT",
    "OP/USDT", "SUI/USDT", "APT/USDT",
]


def run_scan(
    regime: str = "SELECTIVE",
    symbols: list[str] | None = None,
    notify: bool = True,
    webhook_url: str | None = None,
    scan_scalping: bool = True,
    scan_daily: bool = True,
    scan_daytrading: bool = True,
) -> ScanResult:
    """Run all strategies against the symbol list."""
    provider = CryptoProvider()
    targets = symbols or WATCH_SYMBOLS
    result = ScanResult()

    end = pd.Timestamp.now().strftime("%Y-%m-%d")

    # Pre-fetch funding rates for S4 (batch, one API call pattern)
    funding_rates: dict[str, float] = {}
    if scan_scalping:
        try:
            funding_rates = fetch_funding_rates(targets)
        except Exception as e:
            result.errors.append(f"FundingRate fetch: {e}")

    for symbol in targets:
        try:
            # --- Daily strategies (S1, S2) ---
            if scan_daily:
                start_daily = (pd.Timestamp(end) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
                df_daily = provider.fetch_ohlcv(symbol, start_daily, end, "1d")

                for scan_fn in [_scan_watermelon_breakout, _scan_staircase_bounce]:
                    sig = scan_fn(df_daily, symbol, regime)
                    if sig:
                        result.signals.append(sig)

                # --- S4: Funding Rate (uses daily candle for confirmation) ---
                if symbol in funding_rates:
                    sig = scan_funding_rate(
                        df_daily, symbol, funding_rates[symbol], regime,
                    )
                    if sig:
                        result.signals.append(sig)

            # --- Scalping strategies (S3, S6, S7) ---
            if scan_scalping:
                start_5m = (pd.Timestamp(end) - pd.Timedelta(hours=6)).strftime("%Y-%m-%d")
                df_5m = provider.fetch_ohlcv(symbol, start_5m, end, "5m")

                for scan_fn_scalp in [scan_volume_spike, scan_rsi_extreme, scan_momentum]:
                    sig = scan_fn_scalp(df_5m, symbol, "5m")
                    if sig:
                        result.signals.append(sig)

                # --- Daytrading strategies (S8-S11) ---
                if scan_daytrading:
                    for scan_fn_day in [scan_ema_cross, scan_bb_squeeze, scan_key_level_break, scan_candle_surge]:
                        sig = scan_fn_day(df_5m, symbol, "5m")
                        if sig:
                            result.signals.append(sig)

                # S4 with 5m data too (if daily scan is off)
                if not scan_daily and symbol in funding_rates:
                    sig = scan_funding_rate(
                        df_5m, symbol, funding_rates[symbol], regime,
                    )
                    if sig:
                        result.signals.append(sig)

        except Exception as e:
            result.errors.append(f"{symbol}: {e}")
            logger.warning("Scan error for %s: %s", symbol, e)

    # --- Dispatch alerts ---
    if notify and result.signals:
        for sig in result.signals:
            send_signal(sig, webhook_url)

    logger.info(
        "Scan complete: %d signals, %d errors across %d symbols",
        len(result.signals), len(result.errors), len(targets),
    )
    return result

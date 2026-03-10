"""Crypto macro regime engine — determines market exposure based on BTC trend + dominance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from engine.data.provider_crypto import CryptoProvider

class RegimeType(str, Enum):
    ALT_SEASON = "ALT_SEASON"
    BTC_SEASON = "BTC_SEASON"
    SELECTIVE = "SELECTIVE"
    BEAR_MARKET = "BEAR_MARKET"

class BtcTrend(str, Enum):
    UP = "UP"
    DOWN = "DOWN"

class DominanceDir(str, Enum):
    RISING = "RISING"      # BTC outperforming alts → BTC dominant
    FALLING = "FALLING"    # Alts outperforming BTC → alt dominant

# Regime matrix: (BtcTrend, DominanceDir) -> (RegimeType, exposure)
_REGIME_MATRIX: dict[tuple[BtcTrend, DominanceDir], tuple[RegimeType, float]] = {
    (BtcTrend.UP, DominanceDir.FALLING): (RegimeType.ALT_SEASON, 1.0),
    (BtcTrend.UP, DominanceDir.RISING): (RegimeType.BTC_SEASON, 0.2),
    (BtcTrend.DOWN, DominanceDir.FALLING): (RegimeType.SELECTIVE, 0.3),
    (BtcTrend.DOWN, DominanceDir.RISING): (RegimeType.BEAR_MARKET, 0.0),
}

# Top altcoins basket for dominance approximation
DEFAULT_ALT_BASKET: list[str] = [
    "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "DOT/USDT", "LINK/USDT", "MATIC/USDT", "ATOM/USDT",
]

@dataclass
class BtcScoreDetail:
    """Breakdown of the BTC composite score."""
    ema50_above: bool = False      # +1 if close > EMA50
    ema200_above: bool = False     # +1 if close > EMA200
    golden_cross: bool = False     # +1 if EMA50 > EMA200
    rsi_bullish: bool = False      # +1 if RSI > 50
    macd_bullish: bool = False     # +1 if MACD > signal
    score: int = 0                 # sum of above, range -5 to +5

@dataclass
class RegimeState:
    """Snapshot of the current macro regime."""
    regime: RegimeType
    btc_trend: BtcTrend
    dominance_dir: DominanceDir
    exposure: float                # 0.0 ~ 1.0
    btc_score: int                 # -5 ~ +5
    btc_score_detail: BtcScoreDetail
    btc_price: float = 0.0
    alt_basket_return_20d: float = 0.0
    btc_return_20d: float = 0.0
    date: str = ""

class CryptoRegimeEngine:
    """Evaluates the crypto macro regime based on BTC trend and dominance proxy."""

    def __init__(
        self,
        ema_short: int = 50,
        ema_long: int = 200,
        rsi_period: int = 14,
        dominance_period: int = 20,
        alt_basket: list[str] | None = None,
    ) -> None:
        self._ema_short = ema_short
        self._ema_long = ema_long
        self._rsi_period = rsi_period
        self._dominance_period = dominance_period
        self._alt_basket = alt_basket or DEFAULT_ALT_BASKET
        self._provider = CryptoProvider()

    def _fetch_btc(self, start: str, end: str, timeframe: str = "1d") -> pd.DataFrame:
        """Fetch BTC/USDT OHLCV with enough lookback for EMA200."""
        # Need extra bars for indicator warmup (EMA200 needs ~200 bars)
        lookback_start = (pd.Timestamp(start) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
        df = self._provider.fetch_ohlcv("BTC/USDT", lookback_start, end, timeframe)
        return df

    def _compute_btc_score(self, df: pd.DataFrame) -> BtcScoreDetail:
        """Compute BTC composite score from technical indicators on the last bar."""
        close = df["close"]
        last_close = float(close.iloc[-1])

        ema50 = close.ewm(span=self._ema_short, adjust=False).mean()
        ema200 = close.ewm(span=self._ema_long, adjust=False).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self._rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self._rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        last_rsi = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()

        detail = BtcScoreDetail()
        score = 0

        # EMA50 above
        if last_close > float(ema50.iloc[-1]):
            detail.ema50_above = True
            score += 1
        else:
            score -= 1

        # EMA200 above
        if last_close > float(ema200.iloc[-1]):
            detail.ema200_above = True
            score += 1
        else:
            score -= 1

        # Golden cross (EMA50 > EMA200)
        if float(ema50.iloc[-1]) > float(ema200.iloc[-1]):
            detail.golden_cross = True
            score += 1
        else:
            score -= 1

        # RSI bullish
        if last_rsi > 50:
            detail.rsi_bullish = True
            score += 1
        else:
            score -= 1

        # MACD bullish
        if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]):
            detail.macd_bullish = True
            score += 1
        else:
            score -= 1

        detail.score = score
        return detail

    def _compute_dominance(self, btc_df: pd.DataFrame, end: str) -> tuple[DominanceDir, float, float]:
        """Approximate dominance by comparing BTC vs alt basket returns over N days."""
        period = self._dominance_period
        if len(btc_df) < period + 1:
            return DominanceDir.RISING, 0.0, 0.0

        btc_close = btc_df["close"]
        btc_return = (float(btc_close.iloc[-1]) / float(btc_close.iloc[-period - 1])) - 1.0

        # Fetch alt basket returns
        alt_returns: list[float] = []
        lookback_start = (pd.Timestamp(end) - pd.Timedelta(days=period + 10)).strftime("%Y-%m-%d")
        for symbol in self._alt_basket:
            try:
                alt_df = self._provider.fetch_ohlcv(symbol, lookback_start, end, "1d")
                if len(alt_df) >= period + 1:
                    alt_close = alt_df["close"]
                    ret = (float(alt_close.iloc[-1]) / float(alt_close.iloc[-period - 1])) - 1.0
                    alt_returns.append(ret)
            except Exception:
                continue

        if not alt_returns:
            return DominanceDir.RISING, btc_return, 0.0

        avg_alt_return = sum(alt_returns) / len(alt_returns)

        # If BTC outperforms alts → dominance RISING (BTC dominant)
        # If alts outperform BTC → dominance FALLING (alt dominant)
        if btc_return > avg_alt_return:
            return DominanceDir.RISING, btc_return, avg_alt_return
        else:
            return DominanceDir.FALLING, btc_return, avg_alt_return

    def evaluate(self, date: str | None = None) -> RegimeState:
        """Evaluate the regime for a given date (default: today)."""
        if date is None:
            end = pd.Timestamp.now().strftime("%Y-%m-%d")
        else:
            end = date

        btc_df = self._fetch_btc("2020-01-01", end)
        if btc_df.empty:
            return RegimeState(
                regime=RegimeType.BEAR_MARKET,
                btc_trend=BtcTrend.DOWN,
                dominance_dir=DominanceDir.RISING,
                exposure=0.0,
                btc_score=-5,
                btc_score_detail=BtcScoreDetail(score=-5),
                date=end,
            )

        # BTC score
        score_detail = self._compute_btc_score(btc_df)

        # BTC trend from EMA50
        ema50 = btc_df["close"].ewm(span=self._ema_short, adjust=False).mean()
        last_close = float(btc_df["close"].iloc[-1])
        btc_trend = BtcTrend.UP if last_close > float(ema50.iloc[-1]) else BtcTrend.DOWN

        # Dominance
        dominance_dir, btc_ret, alt_ret = self._compute_dominance(btc_df, end)

        # Regime from matrix
        regime, exposure = _REGIME_MATRIX[(btc_trend, dominance_dir)]

        return RegimeState(
            regime=regime,
            btc_trend=btc_trend,
            dominance_dir=dominance_dir,
            exposure=exposure,
            btc_score=score_detail.score,
            btc_score_detail=score_detail,
            btc_price=last_close,
            btc_return_20d=round(btc_ret * 100, 2),
            alt_basket_return_20d=round(alt_ret * 100, 2),
            date=end,
        )

    def evaluate_series(self, start: str, end: str, timeframe: str = "1d") -> pd.DataFrame:
        """Generate daily regime + exposure for a date range (for backtesting).

        Returns DataFrame with columns: date, regime, exposure, btc_trend, dominance_dir, btc_score
        """
        btc_df = self._fetch_btc(start, end, timeframe)
        if btc_df.empty:
            return pd.DataFrame()

        close = btc_df["close"]
        ema50 = close.ewm(span=self._ema_short, adjust=False).mean()
        ema200 = close.ewm(span=self._ema_long, adjust=False).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self._rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self._rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()

        # Alt basket average close series
        period = self._dominance_period
        lookback_start = (pd.Timestamp(start) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
        alt_dfs: list[pd.Series] = []
        for symbol in self._alt_basket:
            try:
                alt_df = self._provider.fetch_ohlcv(symbol, lookback_start, end, timeframe)
                if not alt_df.empty:
                    alt_dfs.append(alt_df["close"])
            except Exception:
                continue

        # Build row-by-row from the requested start onwards
        start_ts = pd.Timestamp(start, tz="UTC")
        mask = btc_df.index >= start_ts
        eval_df = btc_df[mask].copy()

        regimes: list[str] = []
        exposures: list[float] = []
        btc_trends: list[str] = []
        dominance_dirs: list[str] = []
        btc_scores: list[int] = []

        for idx in eval_df.index:
            loc = btc_df.index.get_loc(idx)
            c = float(close.iloc[loc])

            # BTC trend
            trend = BtcTrend.UP if c > float(ema50.iloc[loc]) else BtcTrend.DOWN

            # BTC score
            score = 0
            if c > float(ema50.iloc[loc]): score += 1
            else: score -= 1
            if c > float(ema200.iloc[loc]): score += 1
            else: score -= 1
            if float(ema50.iloc[loc]) > float(ema200.iloc[loc]): score += 1
            else: score -= 1
            rsi_val = float(rsi.iloc[loc]) if not np.isnan(rsi.iloc[loc]) else 50.0
            if rsi_val > 50: score += 1
            else: score -= 1
            if float(macd_line.iloc[loc]) > float(signal_line.iloc[loc]): score += 1
            else: score -= 1

            # Dominance approximation
            if loc >= period:
                btc_ret = (c / float(close.iloc[loc - period])) - 1.0
                alt_rets: list[float] = []
                for alt_s in alt_dfs:
                    # Find nearest index
                    try:
                        alt_current = alt_s.asof(idx)
                        past_idx = btc_df.index[loc - period]
                        alt_past = alt_s.asof(past_idx)
                        if pd.notna(alt_current) and pd.notna(alt_past) and alt_past > 0:
                            alt_rets.append((float(alt_current) / float(alt_past)) - 1.0)
                    except Exception:
                        continue
                avg_alt_ret = sum(alt_rets) / len(alt_rets) if alt_rets else 0.0
                dom = DominanceDir.RISING if btc_ret > avg_alt_ret else DominanceDir.FALLING
            else:
                dom = DominanceDir.RISING

            regime, exposure = _REGIME_MATRIX[(trend, dom)]
            regimes.append(regime.value)
            exposures.append(exposure)
            btc_trends.append(trend.value)
            dominance_dirs.append(dom.value)
            btc_scores.append(score)

        result = pd.DataFrame({
            "date": [str(idx)[:10] for idx in eval_df.index],
            "regime": regimes,
            "exposure": exposures,
            "btc_trend": btc_trends,
            "dominance_dir": dominance_dirs,
            "btc_score": btc_scores,
        }, index=eval_df.index)

        return result

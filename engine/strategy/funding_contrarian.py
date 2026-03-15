"""BTC_선물_봇 v2 — BaseBot 기반 리팩토링.

기존 funding_contrarian.py의 전략 로직만 남기고,
상태관리/루프/알림은 BaseBot에 위임.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import talib

from engine.data.provider_crypto import CryptoProvider, fetch_funding_rate
from engine.strategy.base_bot import BaseBot, BaseBotConfig, BasePosition, TradeRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclass
class FundingContrarianConfig(BaseBotConfig):
    """BTC_선물_봇 설정."""
    bot_name: str = "BTC_선물_봇"
    symbol: str = "BTC/USDT"
    futures_symbol: str = "BTC/USDT:USDT"
    fr_zscore_threshold: float = 1.5
    fr_lookback: int = 150
    ema_fast: int = 20
    ema_slow: int = 50
    hold_hours: float = 50.0
    sl_pct: float = 5.0
    cooldown_hours: float = 24.0
    leverage: int = 3
    state_file: str = "state/funding_contrarian_state.json"


# ---------------------------------------------------------------------------
# 스캐너 (전략 로직)
# ---------------------------------------------------------------------------

class FundingContrarianScanner:
    """펀딩비 역발상 스캐너 — 이벤트 기반."""

    def __init__(self, config: FundingContrarianConfig) -> None:
        self.config = config
        self.fr_history: list[float] = []
        self._in_event: bool = False

    def update_funding_rate(self, rate: float) -> None:
        self.fr_history.append(rate)
        max_len = self.config.fr_lookback + 50
        if len(self.fr_history) > max_len:
            self.fr_history = self.fr_history[-max_len:]

    def calc_fr_zscore(self) -> float | None:
        if len(self.fr_history) < self.config.fr_lookback:
            return None
        window = self.fr_history[-self.config.fr_lookback:]
        mean = float(np.mean(window))
        std = float(np.std(window))
        if std < 1e-10:
            return 0.0
        return (self.fr_history[-1] - mean) / std

    def check_event(self, zscore: float) -> str:
        threshold = self.config.fr_zscore_threshold
        is_extreme = abs(zscore) > threshold
        if is_extreme and not self._in_event:
            self._in_event = True
            return "event_start"
        elif is_extreme and self._in_event:
            return "event_continue"
        elif not is_extreme and self._in_event:
            self._in_event = False
            return "event_end"
        return "no_event"

    def scan(self, df: pd.DataFrame, fr_zscore: float | None = None) -> dict | None:
        """진입 신호. Returns {side, entry_price, stop_loss, fr_zscore} or None."""
        cfg = self.config
        if len(df) < cfg.ema_slow + 10:
            return None

        zscore = fr_zscore if fr_zscore is not None else self.calc_fr_zscore()
        if zscore is None:
            return None

        if self.check_event(zscore) != "event_start":
            return None

        close = df["close"].values.astype(np.float64)
        ema_fast = talib.EMA(close, timeperiod=cfg.ema_fast)
        ema_slow = talib.EMA(close, timeperiod=cfg.ema_slow)
        if np.isnan(ema_fast[-1]) or np.isnan(ema_slow[-1]):
            return None

        side = "SHORT" if zscore > 0 else "LONG"
        entry_price = float(close[-1])
        if side == "LONG":
            stop_loss = entry_price * (1 - cfg.sl_pct / 100)
        else:
            stop_loss = entry_price * (1 + cfg.sl_pct / 100)

        return {
            "side": side,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "fr_zscore": round(zscore, 2),
        }

    def bootstrap(self) -> None:
        """시작 시 과거 펀딩비 API 로드."""
        try:
            from engine.data.provider_crypto import _build_futures_exchange
            ex = _build_futures_exchange(self.config.exchange)
            since = int((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)).timestamp() * 1000)
            all_fr = []
            for _ in range(10):
                fr = ex.fetch_funding_rate_history(self.config.futures_symbol, since=since, limit=1000)
                if not fr:
                    break
                all_fr.extend(fr)
                since = fr[-1]["timestamp"] + 1
                time.sleep(0.3)
            rates = [float(r.get("fundingRate", 0)) for r in all_fr]
            if rates:
                self.fr_history = rates
                logger.info("펀딩비 부트스트랩: %d건", len(rates))
        except Exception as e:
            logger.error("펀딩비 부트스트랩 실패: %s", e)


# ---------------------------------------------------------------------------
# 봇 (BaseBot 상속)
# ---------------------------------------------------------------------------

class FundingContrarianBot(BaseBot):
    """BTC_선물_봇 — BaseBot 기반."""

    def __init__(self, config: FundingContrarianConfig | None = None) -> None:
        self.cfg = config or FundingContrarianConfig()
        super().__init__(self.cfg)
        self.scanner = FundingContrarianScanner(self.cfg)
        self.position: BasePosition | None = None
        self.cooldown_until: str = ""
        self._provider = CryptoProvider(self.cfg.exchange)

    def on_init(self) -> None:
        self.scanner.bootstrap()

    def on_step(self) -> None:
        # 펀딩비 업데이트
        fr = fetch_funding_rate(self.cfg.futures_symbol)
        if fr is not None:
            last = self.scanner.fr_history[-1] if self.scanner.fr_history else None
            if last is None or abs(fr - last) > 1e-10:
                self.scanner.update_funding_rate(fr)

        # OHLCV
        end = pd.Timestamp.now(tz="UTC")
        start = end - pd.Timedelta(hours=100)
        df = self._provider.fetch_ohlcv(self.cfg.symbol, str(start), str(end), "1h")
        if len(df) < 60:
            return

        high = float(df["high"].iloc[-1])
        low = float(df["low"].iloc[-1])
        close = float(df["close"].iloc[-1])

        # 포지션 청산 체크
        if self.position is not None:
            should, reason, exit_price = self.position.check_exit(high, low, close)
            if should:
                if self.position.side == "LONG":
                    pnl = (exit_price - self.position.entry_price) / self.position.entry_price * 100
                else:
                    pnl = (self.position.entry_price - exit_price) / self.position.entry_price * 100
                pnl_lev = pnl * self.cfg.leverage

                self._record_trade(TradeRecord(
                    symbol=self.cfg.symbol, side=self.position.side,
                    entry_price=self.position.entry_price, exit_price=exit_price,
                    pnl_pct=round(pnl_lev, 3), bars_held=self.position.bars_held,
                    reason=reason, entry_time=self.position.entry_time,
                    exit_time=datetime.now(timezone.utc).isoformat(),
                    extra={"leverage": self.cfg.leverage, "pnl_raw": round(pnl, 3)},
                ))
                self.cooldown_until = (
                    datetime.now(timezone.utc) + pd.Timedelta(hours=self.cfg.cooldown_hours)
                ).isoformat()
                self.position = None
            else:
                self.position.tick()

        # 쿨다운 체크
        if self.cooldown_until:
            try:
                if datetime.now(timezone.utc) < datetime.fromisoformat(self.cooldown_until):
                    return
                self.cooldown_until = ""
            except Exception:
                self.cooldown_until = ""

        # 신호 체크
        if self.position is None:
            zscore = self.scanner.calc_fr_zscore()
            if zscore is not None:
                signal = self.scanner.scan(df, fr_zscore=zscore)
                if signal is not None:
                    now = datetime.now(timezone.utc).isoformat()
                    self.position = BasePosition(
                        symbol=self.cfg.symbol,
                        side=signal["side"],
                        entry_price=signal["entry_price"],
                        stop_loss=signal["stop_loss"],
                        max_hold_hours=self.cfg.hold_hours,
                        entry_time=now,
                        extra={"fr_zscore": signal["fr_zscore"], "leverage": self.cfg.leverage},
                    )
                    self._alert_entry(
                        self.cfg.symbol, signal["side"], signal["entry_price"],
                        SL=f"{signal['stop_loss']:.2f}",
                        FR_z=signal["fr_zscore"],
                        레버리지=f"{self.cfg.leverage}x",
                    )

    def get_state_data(self) -> dict:
        return {
            "position": self.position.to_dict() if self.position else None,
            "cooldown_until": self.cooldown_until,
            "fr_history": self.scanner.fr_history[-200:],
        }

    def load_state_data(self, data: dict) -> None:
        if data.get("position"):
            self.position = BasePosition.from_dict(data["position"])
        self.cooldown_until = data.get("cooldown_until", "")
        fr_hist = data.get("fr_history", [])
        if len(fr_hist) >= self.cfg.fr_lookback:
            self.scanner.fr_history = fr_hist
        else:
            self.scanner.bootstrap()

    def summary(self) -> dict:
        pnls = [t["pnl_pct"] for t in self.trade_log] if self.trade_log else []
        wins = [p for p in pnls if p > 0]
        return {
            "trades": len(self.trade_log),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "cumulative": round(sum(pnls), 2) if pnls else 0,
            "position": self.position.to_dict() if self.position else None,
            "cooldown_until": self.cooldown_until,
            "fr_zscore": self.scanner.calc_fr_zscore(),
            "fr_history_len": len(self.scanner.fr_history),
            "mode": self.cfg.mode,
            "leverage": self.cfg.leverage,
        }

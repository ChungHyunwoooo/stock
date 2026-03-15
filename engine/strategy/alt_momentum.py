"""알트_데일리_봇 v2 — BaseBot 기반 리팩토링.

급등 감지 + 모멘텀 편승 (당일 완결).
상태관리/루프/알림은 BaseBot에 위임.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from engine.data.provider_crypto import CryptoProvider
from engine.strategy.base_bot import BaseBot, BaseBotConfig, BasePosition, TradeRecord

logger = logging.getLogger(__name__)


# Walk-forward 통과 58개
VALIDATED_SYMBOLS = [
    "BANANAS31/USDT","GUN/USDT","ZKP/USDT","ZBT/USDT","RESOLV/USDT",
    "TST/USDT","GIGGLE/USDT","VIRTUAL/USDT","SXT/USDT","PARTI/USDT",
    "RONIN/USDT","MIRA/USDT","DOLO/USDT","LQTY/USDT","BARD/USDT",
    "AUCTION/USDT","THE/USDT","HOLO/USDT","KMNO/USDT","SAND/USDT",
    "SEI/USDT","INIT/USDT","ERA/USDT","PIXEL/USDT","DIA/USDT",
    "D/USDT","LINK/USDT","1000SATS/USDT","SUI/USDT","CRV/USDT",
    "PEOPLE/USDT","TREE/USDT","AVAX/USDT","W/USDT","ID/USDT",
    "C98/USDT","WCT/USDT","YB/USDT","FIL/USDT","XRP/USDT",
    "HFT/USDT","KERNEL/USDT","MLN/USDT","ZIL/USDT","FIO/USDT",
    "CAKE/USDT","SUN/USDT","AVA/USDT","XLM/USDT","ADA/USDT",
    "WLFI/USDT","GMT/USDT","ME/USDT","FUN/USDT","HAEDAL/USDT",
    "SENT/USDT","ONDO/USDT","WLD/USDT",
]


@dataclass
class AltMomentumConfig(BaseBotConfig):
    """알트 데일리 봇 설정."""
    bot_name: str = "알트_데일리_봇"
    symbols: list[str] = field(default_factory=lambda: VALIDATED_SYMBOLS.copy())
    pump_threshold: float = 2.0
    vol_multiplier: float = 2.0
    tp_pct: float = 5.0
    sl_pct: float = 3.0
    hold_hours: float = 3.0
    vol_ma_period: int = 20
    max_positions: int = 5
    state_file: str = "state/alt_momentum_state.json"


class AltMomentumBot(BaseBot):
    """알트 데일리 모멘텀 봇 — BaseBot 기반."""

    def __init__(self, config: AltMomentumConfig | None = None) -> None:
        self.cfg = config or AltMomentumConfig()
        super().__init__(self.cfg)
        self.positions: dict[str, BasePosition] = {}
        self._provider = CryptoProvider(self.cfg.exchange)

    def on_init(self) -> None:
        pass  # 초기화 불필요 (펀딩비 부트스트랩 없음)

    def _fetch_latest(self, symbol: str) -> dict | None:
        try:
            end = pd.Timestamp.now(tz="UTC")
            start = end - pd.Timedelta(hours=30)
            df = self._provider.fetch_ohlcv(symbol, str(start), str(end), "1h")
            if len(df) < 2:
                return None
            last = df.iloc[-1]
            prev = df.iloc[-2]
            return {
                "close": float(last["close"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "volume": float(last["volume"]),
                "prev_close": float(prev["close"]),
                "vol_history": df["volume"].values[-self.cfg.vol_ma_period:].tolist(),
            }
        except Exception:
            return None

    def _check_pump(self, data: dict) -> bool:
        if data["prev_close"] <= 0:
            return False
        ret_1h = (data["close"] - data["prev_close"]) / data["prev_close"] * 100
        if ret_1h < self.cfg.pump_threshold:
            return False
        vol_ma = np.mean(data["vol_history"]) if len(data["vol_history"]) >= 10 else 0
        if vol_ma <= 0 or data["volume"] < vol_ma * self.cfg.vol_multiplier:
            return False
        return True

    def on_step(self) -> None:
        cfg = self.cfg

        # 1. 기존 포지션 청산 체크
        closed = []
        for sym, pos in list(self.positions.items()):
            data = self._fetch_latest(sym)
            if data is None:
                pos.tick()
                continue

            should, reason, exit_price = pos.check_exit(data["high"], data["low"], data["close"])
            if should:
                pnl = (exit_price - pos.entry_price) / pos.entry_price * 100
                self._record_trade(TradeRecord(
                    symbol=sym, side="LONG",
                    entry_price=pos.entry_price, exit_price=exit_price,
                    pnl_pct=round(pnl, 3), bars_held=pos.bars_held,
                    reason=reason, entry_time=pos.entry_time,
                    exit_time=datetime.now(timezone.utc).isoformat(),
                ))
                closed.append(sym)
            else:
                pos.tick()

        for sym in closed:
            del self.positions[sym]

        # 2. 신규 진입
        if len(self.positions) >= cfg.max_positions:
            return

        for sym in cfg.symbols:
            if sym in self.positions or len(self.positions) >= cfg.max_positions:
                continue
            data = self._fetch_latest(sym)
            if data is None:
                continue

            if self._check_pump(data):
                entry = data["close"]
                now = datetime.now(timezone.utc).isoformat()
                self.positions[sym] = BasePosition(
                    symbol=sym, side="LONG",
                    entry_price=entry,
                    stop_loss=round(entry * (1 - cfg.sl_pct / 100), 10),
                    take_profit=round(entry * (1 + cfg.tp_pct / 100), 10),
                    max_hold_hours=cfg.hold_hours,
                    entry_time=now,
                )
                self._alert_entry(sym, "LONG", entry,
                    TP=f"{entry * (1 + cfg.tp_pct / 100):.10g}",
                    SL=f"{entry * (1 - cfg.sl_pct / 100):.10g}",
                )
            time.sleep(0.1)

    def get_state_data(self) -> dict:
        return {
            "positions": [p.to_dict() for p in self.positions.values()],
        }

    def load_state_data(self, data: dict) -> None:
        for pd_ in data.get("positions", []):
            pos = BasePosition.from_dict(pd_)
            self.positions[pos.symbol] = pos

    def summary(self) -> dict:
        pnls = [t["pnl_pct"] for t in self.trade_log] if self.trade_log else []
        wins = [p for p in pnls if p > 0]
        return {
            "trades": len(self.trade_log),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "cumulative": round(sum(pnls), 2) if pnls else 0,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "position_count": len(self.positions),
            "mode": self.cfg.mode,
        }

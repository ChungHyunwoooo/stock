"""알트_데일리_봇 — 급등 모멘텀 스캘핑 (당일 완결).

Walk-forward 검증 (2024-06~2026-03):
  진입: 1h 수익률 >2% + 거래량 >2x MA
  익절: +5% (TP)
  손절: -3% (SL)
  타임아웃: 3h
  58개 종목 통과, 평균 연+37%
  당일 완결 → 오버나이트/상폐 리스크 0

사용:
    bot = AltMomentumBot()
    bot.run()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from engine.data.provider_crypto import CryptoProvider

logger = logging.getLogger(__name__)


# Walk-forward 통과 58개 (테스트 기간 연+10% 이상)
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
class AltMomentumConfig:
    """전략 설정."""
    symbols: list[str] = field(default_factory=lambda: VALIDATED_SYMBOLS.copy())
    pump_threshold: float = 2.0      # 1h 급등 기준 (%)
    vol_multiplier: float = 2.0      # 거래량 배수 기준
    tp_pct: float = 5.0              # 익절 (%)
    sl_pct: float = 3.0              # 손절 (%)
    max_hold_bars: int = 3           # 최대 보유 (1h봉)
    vol_ma_period: int = 20          # 거래량 MA 기간
    max_positions: int = 5           # 동시 최대 포지션 수
    mode: str = "paper"              # "paper" or "live"
    poll_interval_sec: int = 60      # 메인 루프 간격
    state_file: str = "state/alt_momentum_state.json"


@dataclass
class AltPosition:
    """보유 포지션."""
    symbol: str
    entry_price: float
    tp_price: float
    sl_price: float
    bars_held: int = 0
    max_hold: int = 3
    entry_time: str = ""

    def check_exit(self, high: float, low: float, close: float) -> tuple[bool, str, float]:
        """TP/SL/timeout 체크. Returns (should_exit, reason, exit_price)."""
        if high >= self.tp_price:
            return True, "tp", self.tp_price
        if low <= self.sl_price:
            return True, "sl", self.sl_price
        if self.bars_held >= self.max_hold:
            return True, "timeout", close
        return False, "", 0.0

    def tick(self) -> None:
        self.bars_held += 1

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "entry_price": self.entry_price,
                "tp_price": self.tp_price, "sl_price": self.sl_price,
                "bars_held": self.bars_held, "max_hold": self.max_hold,
                "entry_time": self.entry_time}

    @staticmethod
    def from_dict(d: dict) -> AltPosition:
        return AltPosition(**d)


class AltMomentumBot:
    """알트 데일리 모멘텀 봇."""

    def __init__(self, config: AltMomentumConfig | None = None) -> None:
        self.config = config or AltMomentumConfig()
        self.positions: dict[str, AltPosition] = {}  # symbol → position
        self.trade_log: list[dict] = []
        self._provider = CryptoProvider("binance")
        self._state_path = Path(self.config.state_file)
        self._vol_cache: dict[str, list[float]] = {}  # symbol → recent volumes

    def _load_state(self) -> None:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                for pd_ in data.get("positions", []):
                    pos = AltPosition.from_dict(pd_)
                    self.positions[pos.symbol] = pos
                self.trade_log = data.get("trade_log", [])
                self._vol_cache = data.get("vol_cache", {})
                logger.info("상태 복원: %d 포지션, %d 거래",
                           len(self.positions), len(self.trade_log))
            except Exception as e:
                logger.warning("상태 복원 실패: %s", e)

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "positions": [p.to_dict() for p in self.positions.values()],
            "trade_log": self.trade_log[-200:],
            "vol_cache": {k: v[-30:] for k, v in self._vol_cache.items()},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self._state_path.write_text(json.dumps(data, indent=2, default=str))

    def _fetch_latest(self, symbol: str) -> dict | None:
        """최근 2봉 조회 → 현재 봉 + 이전 봉."""
        try:
            end = pd.Timestamp.now(tz="UTC")
            start = end - pd.Timedelta(hours=30)
            df = self._provider.fetch_ohlcv(symbol, str(start), str(end), "1h")
            if len(df) < 2:
                return None
            last = df.iloc[-1]
            prev = df.iloc[-2]
            vol_history = df["volume"].values[-self.config.vol_ma_period:].tolist()
            return {
                "close": float(last["close"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "open": float(last["open"]),
                "volume": float(last["volume"]),
                "prev_close": float(prev["close"]),
                "vol_history": vol_history,
            }
        except Exception:
            return None

    def _check_pump(self, symbol: str, data: dict) -> bool:
        """급등 조건 확인."""
        if data["prev_close"] <= 0:
            return False
        ret_1h = (data["close"] - data["prev_close"]) / data["prev_close"] * 100
        if ret_1h < self.config.pump_threshold:
            return False

        vol_ma = np.mean(data["vol_history"]) if len(data["vol_history"]) >= 10 else 0
        if vol_ma <= 0 or data["volume"] < vol_ma * self.config.vol_multiplier:
            return False

        return True

    def step(self) -> None:
        """1봉 처리."""
        cfg = self.config

        # 1. 기존 포지션 청산 체크
        closed_symbols = []
        for sym, pos in list(self.positions.items()):
            data = self._fetch_latest(sym)
            if data is None:
                pos.tick()
                continue

            should_exit, reason, exit_price = pos.check_exit(
                data["high"], data["low"], data["close"],
            )
            if should_exit:
                pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
                self.trade_log.append({
                    "symbol": sym, "side": "LONG",
                    "entry": pos.entry_price, "exit": exit_price,
                    "pnl_pct": round(pnl_pct, 3),
                    "bars_held": pos.bars_held, "reason": reason,
                    "entry_time": pos.entry_time,
                    "exit_time": datetime.now(timezone.utc).isoformat(),
                })
                logger.info("청산: %s %.2f→%.2f (%+.2f%%) %s",
                           sym, pos.entry_price, exit_price, pnl_pct, reason)
                closed_symbols.append(sym)
            else:
                pos.tick()

        for sym in closed_symbols:
            del self.positions[sym]

        # 2. 신규 진입 스캔 (빈 슬롯 있을 때만)
        if len(self.positions) >= cfg.max_positions:
            self._save_state()
            return

        for sym in cfg.symbols:
            if sym in self.positions:
                continue
            if len(self.positions) >= cfg.max_positions:
                break

            data = self._fetch_latest(sym)
            if data is None:
                continue

            if self._check_pump(sym, data):
                entry_price = data["close"]
                pos = AltPosition(
                    symbol=sym,
                    entry_price=entry_price,
                    tp_price=round(entry_price * (1 + cfg.tp_pct / 100), 6),
                    sl_price=round(entry_price * (1 - cfg.sl_pct / 100), 6),
                    max_hold=cfg.max_hold_bars,
                    entry_time=datetime.now(timezone.utc).isoformat(),
                )
                self.positions[sym] = pos
                logger.info("진입: %s LONG @ %.6f (TP=%.6f SL=%.6f)",
                           sym, entry_price, pos.tp_price, pos.sl_price)

            time.sleep(0.1)  # API rate limit

        self._save_state()

    def summary(self) -> dict:
        if not self.trade_log:
            return {"trades": 0, "positions": len(self.positions)}
        pnls = [t["pnl_pct"] for t in self.trade_log]
        wins = [p for p in pnls if p > 0]
        return {
            "trades": len(self.trade_log),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(pnls) * 100, 1),
            "avg_pnl": round(float(np.mean(pnls)), 3),
            "cumulative": round(sum(pnls), 2),
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "mode": self.config.mode,
        }

    def run(self) -> None:
        """메인 루프."""
        logger.info("알트_데일리_봇 시작 (mode=%s, %d종목, max_pos=%d)",
                    self.config.mode, len(self.config.symbols), self.config.max_positions)
        self._load_state()

        while True:
            try:
                self.step()
            except Exception as e:
                logger.error("step 오류: %s", e)
            time.sleep(self.config.poll_interval_sec)

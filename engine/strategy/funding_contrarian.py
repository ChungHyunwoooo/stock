"""BTC_선물_봇 — 펀딩비 역발상 전략 (이벤트 기반).

검증 결과 (BTC 1h, 2024-01~2026-03, 이벤트 기반 중복 제거):
  진입: 펀딩비 z-score > 1.5 이벤트 시작 시 역방향
  보유: 50봉 (약 50시간)
  손절: -5% (고정)
  쿨다운: 24봉 (이전 거래 종료 후 최소 대기)
  레버리지: 3x (Kelly 최적 3.2x)

  137건/2년, 승률 56.9%, 손익비 0.98
  3x 기준: 연 +70.9%, MDD -60.9%
  BTC 전용 (ETH/SOL/알트 불가 — 변동성 차이)

사용:
    from engine.strategy.funding_contrarian import FundingContrarianBot
    bot = FundingContrarianBot()
    bot.run()  # 페이퍼 모드
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
import talib

from engine.data.provider_crypto import (
    CryptoProvider,
    fetch_funding_rate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclass
class FundingContrarianConfig:
    """전략 설정 — 검증된 파라미터."""
    symbol: str = "BTC/USDT"
    futures_symbol: str = "BTC/USDT:USDT"
    fr_zscore_threshold: float = 1.5
    fr_lookback: int = 150              # z-score 롤링 윈도우 (펀딩비 개수)
    ema_fast: int = 20
    ema_slow: int = 50
    hold_bars: int = 50                 # 최대 보유 (1h봉 수)
    sl_pct: float = 5.0                 # 손절 (%)
    cooldown_bars: int = 24             # 거래 후 최소 대기 (봉)
    leverage: int = 3
    mode: str = "paper"                 # "paper" or "live"
    poll_interval_sec: int = 60         # 메인 루프 간격 (초)
    state_file: str = "state/funding_contrarian_state.json"


# ---------------------------------------------------------------------------
# 신호 + 포지션
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Signal:
    """진입 신호."""
    symbol: str
    side: str               # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    hold_bars: int
    fr_zscore: float
    reason: str
    timestamp: str


@dataclass
class Position:
    """보유 포지션 상태."""
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    bars_held: int = 0
    max_hold: int = 50
    entry_time: str = ""

    def should_exit(self, current_high: float, current_low: float) -> tuple[bool, str]:
        # 시간 기반 timeout (max_hold = 시간 단위)
        if self.entry_time:
            from datetime import datetime, timezone
            try:
                entry_dt = datetime.fromisoformat(self.entry_time)
                elapsed_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
                if elapsed_hours >= self.max_hold:
                    return True, "hold_timeout"
            except Exception:
                pass
        if self.side == "LONG" and current_low <= self.stop_loss:
            return True, "stop_loss"
        if self.side == "SHORT" and current_high >= self.stop_loss:
            return True, "stop_loss"
        return False, ""

    def tick(self) -> None:
        self.bars_held += 1

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "side": self.side,
            "entry_price": self.entry_price, "stop_loss": self.stop_loss,
            "bars_held": self.bars_held, "max_hold": self.max_hold,
            "entry_time": self.entry_time,
        }

    @staticmethod
    def from_dict(d: dict) -> Position:
        return Position(**d)


# ---------------------------------------------------------------------------
# 스캐너 (이벤트 기반)
# ---------------------------------------------------------------------------

class FundingContrarianScanner:
    """펀딩비 역발상 스캐너 — 이벤트 기반."""

    def __init__(self, config: FundingContrarianConfig) -> None:
        self.config = config
        self._fr_history: list[float] = []
        self._in_event: bool = False
        self._event_zscores: list[float] = []

    def update_funding_rate(self, rate: float) -> None:
        """펀딩비 히스토리 업데이트."""
        self._fr_history.append(rate)
        max_len = self.config.fr_lookback + 50
        if len(self._fr_history) > max_len:
            self._fr_history = self._fr_history[-max_len:]

    def calc_fr_zscore(self) -> float | None:
        """현재 펀딩비 z-score."""
        if len(self._fr_history) < self.config.fr_lookback:
            return None
        window = self._fr_history[-self.config.fr_lookback:]
        mean = float(np.mean(window))
        std = float(np.std(window))
        if std < 1e-10:
            return 0.0
        return (self._fr_history[-1] - mean) / std

    def check_event(self, zscore: float) -> str:
        """이벤트 상태 업데이트.

        Returns:
            "event_start": 이벤트 시작 (진입 시점)
            "event_continue": 이벤트 진행 중
            "event_end": 이벤트 종료
            "no_event": 이벤트 아님
        """
        threshold = self.config.fr_zscore_threshold
        is_extreme = abs(zscore) > threshold

        if is_extreme and not self._in_event:
            self._in_event = True
            self._event_zscores = [zscore]
            return "event_start"
        elif is_extreme and self._in_event:
            self._event_zscores.append(zscore)
            return "event_continue"
        elif not is_extreme and self._in_event:
            self._in_event = False
            self._event_zscores = []
            return "event_end"
        return "no_event"

    def scan(
        self,
        df: pd.DataFrame,
        fr_zscore: float | None = None,
    ) -> Signal | None:
        """진입 신호 확인.

        이벤트 시작 시에만 신호 발생 (중복 진입 방지).
        """
        cfg = self.config

        if len(df) < cfg.ema_slow + 10:
            return None

        zscore = fr_zscore if fr_zscore is not None else self.calc_fr_zscore()
        if zscore is None:
            return None

        # 이벤트 시작이 아니면 스킵
        event_status = self.check_event(zscore)
        if event_status != "event_start":
            return None

        # EMA 방향
        close = df["close"].values.astype(np.float64)
        ema_fast = talib.EMA(close, timeperiod=cfg.ema_fast)
        ema_slow = talib.EMA(close, timeperiod=cfg.ema_slow)

        if np.isnan(ema_fast[-1]) or np.isnan(ema_slow[-1]):
            return None

        # 역발상 방향
        if zscore > 0:
            side = "SHORT"  # 롱 과열 → 숏
        else:
            side = "LONG"   # 숏 과열 → 롱

        entry_price = float(close[-1])
        if side == "LONG":
            stop_loss = round(entry_price * (1 - cfg.sl_pct / 100), 2)
        else:
            stop_loss = round(entry_price * (1 + cfg.sl_pct / 100), 2)

        return Signal(
            symbol=cfg.symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            hold_bars=cfg.hold_bars,
            fr_zscore=round(zscore, 2),
            reason=f"FR z={zscore:.2f} ({'롱과열→숏' if side == 'SHORT' else '숏과열→롱'})",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# 봇 (독립 실행)
# ---------------------------------------------------------------------------

class FundingContrarianBot:
    """BTC_선물_봇 — 독립 실행, 페이퍼/라이브 모드."""

    def __init__(self, config: FundingContrarianConfig | None = None) -> None:
        self.config = config or FundingContrarianConfig()
        self.scanner = FundingContrarianScanner(self.config)
        self.position: Position | None = None
        self.cooldown_remaining: int = 0
        self.trade_log: list[dict] = []
        self._provider = CryptoProvider("binance")
        self._state_path = Path(self.config.state_file)

    def _bootstrap_funding_history(self) -> None:
        """시작 시 과거 펀딩비를 API에서 한번에 로드.

        백테스트와 동일한 조건: 150개 이상의 펀딩비 정산 값.
        8h 간격 → 150개 = 50일치.
        """
        from engine.data.provider_crypto import _build_futures_exchange
        import pandas as pd

        try:
            ex = _build_futures_exchange("binance")
            since = int((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)).timestamp() * 1000)
            all_fr = []
            for _ in range(10):
                fr = ex.fetch_funding_rate_history(
                    self.config.futures_symbol, since=since, limit=1000,
                )
                if not fr:
                    break
                all_fr.extend(fr)
                since = fr[-1]["timestamp"] + 1
                import time as _t
                _t.sleep(0.3)

            rates = [float(r.get("fundingRate", 0)) for r in all_fr]
            if rates:
                self.scanner._fr_history = rates
                logger.info("펀딩비 히스토리 부트스트랩: %d건 (%.0f일)",
                           len(rates), len(rates) * 8 / 24)
            else:
                logger.warning("펀딩비 히스토리 부트스트랩 실패: 0건")
        except Exception as e:
            logger.error("펀딩비 부트스트랩 오류: %s", e)

    def _load_state(self) -> None:
        """상태 복원 (재시작 대비)."""
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                if data.get("position"):
                    self.position = Position.from_dict(data["position"])
                self.cooldown_remaining = data.get("cooldown_remaining", 0)
                fr_hist = data.get("fr_history", [])
                if len(fr_hist) >= self.config.fr_lookback:
                    self.scanner._fr_history = fr_hist
                    logger.info("상태 복원: fr_history=%d (저장된 것 사용)", len(fr_hist))
                else:
                    logger.info("저장된 fr_history 부족(%d), API 부트스트랩", len(fr_hist))
                    self._bootstrap_funding_history()
                self.trade_log = data.get("trade_log", [])
                logger.info("상태 복원: position=%s, cooldown=%d, fr_history=%d",
                           self.position is not None, self.cooldown_remaining,
                           len(self.scanner._fr_history))
            except Exception as e:
                logger.warning("상태 복원 실패: %s", e)
                self._bootstrap_funding_history()
        else:
            self._bootstrap_funding_history()

    def _save_state(self) -> None:
        """상태 저장."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "position": self.position.to_dict() if self.position else None,
            "cooldown_remaining": self.cooldown_remaining,
            "fr_history": self.scanner._fr_history[-200:],
            "trade_log": self.trade_log[-100:],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self._state_path.write_text(json.dumps(data, indent=2, default=str))

    def _fetch_ohlcv(self) -> pd.DataFrame:
        """최근 100봉 1h OHLCV."""
        end = datetime.now(timezone.utc)
        start = end - pd.Timedelta(hours=100)
        return self._provider.fetch_ohlcv(
            self.config.symbol, str(start), str(end), "1h",
        )

    def _fetch_funding_rate(self) -> float | None:
        """현재 펀딩비 조회."""
        return fetch_funding_rate(self.config.futures_symbol)

    def _execute_entry(self, signal: Signal) -> None:
        """진입 실행 (페이퍼 or 라이브)."""
        self.position = Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            max_hold=signal.hold_bars,
            entry_time=signal.timestamp,
        )
        logger.info("진입: %s %s @ %.2f (SL=%.2f, z=%.2f) [%s]",
                    signal.side, signal.symbol, signal.entry_price,
                    signal.stop_loss, signal.fr_zscore, self.config.mode)
        try:
            from engine.notifications.bot_alert import alert_entry
            alert_entry("BTC_선물_봇", signal.symbol, signal.side, signal.entry_price,
                       SL=f"${signal.stop_loss:,.2f}", FR_z=signal.fr_zscore,
                       레버리지=f"{self.config.leverage}x")
        except Exception:
            pass

    def _execute_exit(self, exit_price: float, reason: str) -> None:
        """청산 실행."""
        if self.position is None:
            return

        if self.position.side == "LONG":
            pnl_pct = (exit_price - self.position.entry_price) / self.position.entry_price * 100
        else:
            pnl_pct = (self.position.entry_price - exit_price) / self.position.entry_price * 100

        pnl_pct_leveraged = pnl_pct * self.config.leverage

        trade = {
            "symbol": self.position.symbol,
            "side": self.position.side,
            "entry": self.position.entry_price,
            "exit": exit_price,
            "pnl_pct": round(pnl_pct, 3),
            "pnl_pct_lev": round(pnl_pct_leveraged, 3),
            "bars_held": self.position.bars_held,
            "reason": reason,
            "entry_time": self.position.entry_time,
            "exit_time": datetime.now(timezone.utc).isoformat(),
        }
        self.trade_log.append(trade)
        self.cooldown_remaining = self.config.cooldown_bars

        logger.info("청산: %s %s %.2f→%.2f (%+.2f%%, %dx=%+.2f%%) reason=%s bars=%d",
                    self.position.side, self.position.symbol,
                    self.position.entry_price, exit_price,
                    pnl_pct, self.config.leverage, pnl_pct_leveraged,
                    reason, self.position.bars_held)
        try:
            from engine.notifications.bot_alert import alert_exit
            alert_exit("BTC_선물_봇", self.position.symbol, self.position.side,
                      self.position.entry_price, exit_price, pnl_pct_leveraged,
                      reason, 보유=f"{self.position.bars_held}h",
                      레버리지=f"{self.config.leverage}x")
        except Exception:
            pass

        self.position = None

    def step(self) -> None:
        """1봉(1h) 처리 — 메인 루프에서 호출."""
        # 펀딩비 업데이트: 값이 변경됐을 때만 히스토리에 추가 (8h마다)
        fr = self._fetch_funding_rate()
        if fr is not None:
            last_fr = self.scanner._fr_history[-1] if self.scanner._fr_history else None
            if last_fr is None or abs(fr - last_fr) > 1e-10:
                self.scanner.update_funding_rate(fr)

        # OHLCV
        df = self._fetch_ohlcv()
        if len(df) < 60:
            return

        current_high = float(df["high"].iloc[-1])
        current_low = float(df["low"].iloc[-1])
        current_close = float(df["close"].iloc[-1])

        # 포지션 있으면 청산 체크
        if self.position is not None:
            should_exit, reason = self.position.should_exit(current_high, current_low)
            if should_exit:
                exit_price = self.position.stop_loss if reason == "stop_loss" else current_close
                self._execute_exit(exit_price, reason)
            else:
                self.position.tick()

        # 쿨다운
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        # 신호 체크 (포지션 없고 쿨다운 완료)
        if self.position is None and self.cooldown_remaining <= 0:
            zscore = self.scanner.calc_fr_zscore()
            if zscore is not None:
                signal = self.scanner.scan(df, fr_zscore=zscore)
                if signal is not None:
                    self._execute_entry(signal)

        self._save_state()

    def summary(self) -> dict:
        """현재 상태 요약."""
        if not self.trade_log:
            return {"trades": 0, "position": None}

        pnls = [t["pnl_pct_lev"] for t in self.trade_log]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        return {
            "trades": len(self.trade_log),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "avg_pnl": round(float(np.mean(pnls)), 3) if pnls else 0,
            "cumulative": round(sum(pnls), 2),
            "position": self.position.to_dict() if self.position else None,
            "cooldown": self.cooldown_remaining,
            "fr_history_len": len(self.scanner._fr_history),
            "mode": self.config.mode,
            "leverage": self.config.leverage,
        }

    def run(self) -> None:
        """메인 루프 — 백그라운드 실행용."""
        logger.info("BTC_선물_봇 시작 (mode=%s, leverage=%dx)", self.config.mode, self.config.leverage)
        self._load_state()

        while True:
            try:
                self.step()
            except Exception as e:
                logger.error("step 오류: %s", e)

            time.sleep(self.config.poll_interval_sec)

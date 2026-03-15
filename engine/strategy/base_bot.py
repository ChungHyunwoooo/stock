"""BaseBot — 모든 트레이딩 봇의 공통 추상 클래스.

새 봇 추가 = BaseBot 상속 + scan_signal/execute_entry/execute_exit 구현
상태관리, 로깅, Discord 알림, 루프는 공통.

사용:
    class MyBot(BaseBot):
        def scan_signal(self) -> Signal | None: ...
        def check_position_exit(self) -> tuple[bool, str, float]: ...
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 공통 설정
# ---------------------------------------------------------------------------

@dataclass
class BaseBotConfig:
    """모든 봇의 공통 설정."""
    bot_name: str = "unnamed_bot"
    mode: str = "paper"                     # "paper" | "live"
    poll_interval_sec: int = 60
    state_file: str = "state/bot_state.json"
    exchange: str = "binance"               # 거래소 (추후 멀티 거래소)
    log_file: str = ""                      # 비어있으면 bot_name 기반 자동 생성


# ---------------------------------------------------------------------------
# 공통 포지션
# ---------------------------------------------------------------------------

@dataclass
class BasePosition:
    """공통 포지션 상태."""
    symbol: str
    side: str               # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    bars_held: int = 0
    max_hold_hours: float = 50.0
    entry_time: str = ""
    extra: dict = field(default_factory=dict)  # 봇별 추가 데이터

    def elapsed_hours(self) -> float:
        """진입 후 경과 시간 (시간 단위)."""
        if not self.entry_time:
            return 0.0
        try:
            entry_dt = datetime.fromisoformat(self.entry_time)
            return (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
        except (ValueError, TypeError) as e:
            logger.debug("elapsed_hours 파싱 실패: %s", e)
            return 0.0

    def is_timed_out(self) -> bool:
        """시간 기반 타임아웃 체크."""
        return self.elapsed_hours() >= self.max_hold_hours

    def check_sl(self, current_high: float, current_low: float) -> bool:
        """손절 체크."""
        if self.side == "LONG" and current_low <= self.stop_loss:
            return True
        if self.side == "SHORT" and current_high >= self.stop_loss:
            return True
        return False

    def check_tp(self, current_high: float, current_low: float) -> bool:
        """익절 체크."""
        if self.take_profit is None:
            return False
        if self.side == "LONG" and current_high >= self.take_profit:
            return True
        if self.side == "SHORT" and current_low <= self.take_profit:
            return True
        return False

    def check_exit(self, current_high: float, current_low: float, current_close: float) -> tuple[bool, str, float]:
        """TP/SL/timeout 통합 체크. Returns (should_exit, reason, exit_price)."""
        if self.check_tp(current_high, current_low):
            return True, "tp", self.take_profit
        if self.check_sl(current_high, current_low):
            return True, "sl", self.stop_loss
        if self.is_timed_out():
            return True, "timeout", current_close
        return False, "", 0.0

    def tick(self) -> None:
        self.bars_held += 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BasePosition:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# 공통 거래 기록
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """거래 기록."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    bars_held: int
    reason: str
    entry_time: str
    exit_time: str
    bot_name: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# BaseBot
# ---------------------------------------------------------------------------

class BaseBot(ABC):
    """트레이딩 봇 공통 베이스 클래스."""

    def __init__(self, config: BaseBotConfig) -> None:
        self.config = config
        self.trade_log: list[dict] = []
        self._state_path = Path(config.state_file)

    # --- 서브클래스 구현 필수 ---

    @abstractmethod
    def on_init(self) -> None:
        """봇 시작 시 초기화 (데이터 로드 등)."""

    @abstractmethod
    def on_step(self) -> None:
        """매 poll마다 실행되는 메인 로직."""

    @abstractmethod
    def get_state_data(self) -> dict:
        """상태 저장용 데이터 반환."""

    @abstractmethod
    def load_state_data(self, data: dict) -> None:
        """상태 복원."""

    @abstractmethod
    def summary(self) -> dict:
        """현재 상태 요약."""

    # --- 공통 구현 ---

    def _save_state(self) -> None:
        """상태 파일 저장."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.get_state_data()
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["bot_name"] = self.config.bot_name
        data["trade_log"] = self.trade_log[-200:]
        self._state_path.write_text(json.dumps(data, indent=2, default=str))

    def _load_state(self) -> None:
        """상태 파일 복원."""
        if not self._state_path.exists():
            self.on_init()
            return
        try:
            data = json.loads(self._state_path.read_text())
            self.trade_log = data.get("trade_log", [])
            self.load_state_data(data)
            logger.info("[%s] 상태 복원 완료", self.config.bot_name)
        except Exception as e:
            logger.warning("[%s] 상태 복원 실패: %s — 초기화", self.config.bot_name, e)
            self.on_init()

    def _record_trade(self, record: TradeRecord) -> None:
        """거래 기록 + Discord 알림."""
        record.bot_name = self.config.bot_name
        self.trade_log.append(record.to_dict())
        logger.info("[%s] 청산: %s %s %.6f→%.6f (%+.2f%%) %s",
                    self.config.bot_name, record.side, record.symbol,
                    record.entry_price, record.exit_price,
                    record.pnl_pct, record.reason)
        try:
            from engine.notifications.bot_alert import alert_exit
            alert_exit(self.config.bot_name, record.symbol, record.side,
                      record.entry_price, record.exit_price,
                      record.pnl_pct, record.reason)
        except Exception as e:
            logger.debug("청산 알림 실패: %s", e)

    def _alert_entry(self, symbol: str, side: str, price: float, **extra) -> None:
        """진입 알림."""
        logger.info("[%s] 진입: %s %s @ %.6f", self.config.bot_name, side, symbol, price)
        try:
            from engine.notifications.bot_alert import alert_entry
            alert_entry(self.config.bot_name, symbol, side, price, **extra)
        except Exception as e:
            logger.debug("진입 알림 실패: %s", e)

    def run(self) -> None:
        """메인 루프."""
        logger.info("[%s] 시작 (mode=%s)", self.config.bot_name, self.config.mode)
        self._load_state()

        while True:
            try:
                self.on_step()
                self._save_state()
            except Exception as e:
                logger.error("[%s] step 오류: %s", self.config.bot_name, e)
            time.sleep(self.config.poll_interval_sec)

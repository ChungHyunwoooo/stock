"""리스크 관리 모듈 — 진입 필터 및 포지션 제한.

규칙:
  1. 심볼당 동시 포지션 1개
  2. 일일 최대 손실 제한
  3. 연속 SL 제한 (연속 N회 SL 시 해당 심볼 일시 정지)
  4. 최대 동시 포지션 수 제한
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from engine.strategy.pattern_detector import PatternSignal


@dataclass
class RiskConfig:
    max_positions_per_symbol: int = 1
    max_total_positions: int = 5
    max_daily_loss_pct: float = 5.0       # 일일 최대 손실 (자본 대비 %)
    max_consecutive_sl: int = 3            # 연속 SL 허용 횟수
    cooldown_bars_after_sl: int = 5        # SL 후 재진입 대기 봉 수


@dataclass
class SymbolState:
    open_positions: int = 0
    consecutive_sl: int = 0
    last_sl_bar: int = -999
    daily_pnl_pct: float = 0.0
    daily_trades: int = 0


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self._states: dict[str, SymbolState] = {}
        self._total_positions: int = 0
        self._daily_pnl_pct: float = 0.0
        self._last_reset_date: str = ""

    def _get_state(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState()
        return self._states[symbol]

    def _check_daily_reset(self) -> None:
        """날짜 변경 시 일일 통계 초기화."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._last_reset_date = today
            self._daily_pnl_pct = 0.0
            for state in self._states.values():
                state.daily_pnl_pct = 0.0
                state.daily_trades = 0

    def allow_entry(self, symbol: str, signal: PatternSignal) -> bool:
        """진입 허용 여부 판단."""
        self._check_daily_reset()
        state = self._get_state(symbol)

        # 규칙 1: 심볼당 동시 포지션 제한
        if state.open_positions >= self.config.max_positions_per_symbol:
            return False

        # 규칙 2: 전체 동시 포지션 제한
        if self._total_positions >= self.config.max_total_positions:
            return False

        # 규칙 3: 일일 최대 손실 초과
        if self._daily_pnl_pct <= -self.config.max_daily_loss_pct:
            return False

        # 규칙 4: 연속 SL 제한
        if state.consecutive_sl >= self.config.max_consecutive_sl:
            return False

        # 규칙 5: SL 후 쿨다운
        if signal.bar_index - state.last_sl_bar < self.config.cooldown_bars_after_sl:
            return False

        return True

    def on_entry(self, symbol: str) -> None:
        """진입 시 상태 업데이트."""
        state = self._get_state(symbol)
        state.open_positions += 1
        self._total_positions += 1

    def on_exit(self, symbol: str, pnl_pct: float, exit_reason: str,
                bar_index: int = 0) -> None:
        """청산 시 상태 업데이트."""
        self._check_daily_reset()
        state = self._get_state(symbol)
        state.open_positions = max(0, state.open_positions - 1)
        self._total_positions = max(0, self._total_positions - 1)

        state.daily_pnl_pct += pnl_pct
        self._daily_pnl_pct += pnl_pct
        state.daily_trades += 1

        if exit_reason == "SL":
            state.consecutive_sl += 1
            state.last_sl_bar = bar_index
        else:
            state.consecutive_sl = 0

    def get_status(self) -> dict:
        """현재 리스크 상태 요약."""
        self._check_daily_reset()
        return {
            "total_positions": self._total_positions,
            "daily_pnl_pct": round(self._daily_pnl_pct, 2),
            "symbols": {
                sym: {
                    "open": s.open_positions,
                    "consecutive_sl": s.consecutive_sl,
                    "daily_pnl": round(s.daily_pnl_pct, 2),
                }
                for sym, s in self._states.items()
            },
        }

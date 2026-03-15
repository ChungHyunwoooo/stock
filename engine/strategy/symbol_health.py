"""종목 건강도 모니터 — 실시간 성과 추적 + 자동 제외/복귀.

"되던게 안된다" → 자동 제외 (손실 방지)
"안되던게 된다" → 자동 복귀 (기회 포착)

봇 on_step에서 매 거래 후 호출.

사용:
    monitor = SymbolHealthMonitor(config)
    monitor.record_trade("SUI/USDT", pnl=2.5)
    monitor.record_trade("SUI/USDT", pnl=-3.0)
    if not monitor.is_healthy("SUI/USDT"):
        skip_symbol("SUI/USDT")
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_PATH = Path("state/symbol_health.json")


@dataclass
class SymbolHealthConfig:
    """건강도 판정 설정."""
    max_consecutive_losses: int = 5      # N연패 시 제외
    min_trades_for_eval: int = 5         # 최소 거래 수 (이하면 판정 안 함)
    min_win_rate: float = 35.0           # 승률 이하 제외 (%)
    recovery_trades: int = 3             # 제외 후 재평가 거래 수
    lookback_trades: int = 20            # 최근 N거래로 평가


@dataclass
class SymbolStats:
    """심볼별 통계."""
    trades: list[float] = field(default_factory=list)  # 최근 PnL 리스트
    consecutive_losses: int = 0
    is_excluded: bool = False
    excluded_at: str = ""
    recovery_count: int = 0  # 제외 후 거래 수 (재평가용)

    def record(self, pnl: float) -> None:
        self.trades.append(pnl)
        if len(self.trades) > 50:  # 최대 50건 유지
            self.trades = self.trades[-50:]
        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        if self.is_excluded:
            self.recovery_count += 1

    def win_rate(self, lookback: int = 20) -> float:
        recent = self.trades[-lookback:]
        if not recent:
            return 50.0
        return sum(1 for p in recent if p > 0) / len(recent) * 100

    def avg_pnl(self, lookback: int = 20) -> float:
        recent = self.trades[-lookback:]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)


class SymbolHealthMonitor:
    """종목 건강도 모니터."""

    def __init__(self, config: SymbolHealthConfig | None = None) -> None:
        self.config = config or SymbolHealthConfig()
        self._stats: dict[str, SymbolStats] = defaultdict(SymbolStats)
        self._load_state()

    def record_trade(self, symbol: str, pnl: float) -> None:
        """거래 결과 기록 + 건강도 재평가."""
        stats = self._stats[symbol]
        stats.record(pnl)
        self._evaluate(symbol)
        self._save_state()

    def is_healthy(self, symbol: str) -> bool:
        """해당 심볼에 진입해도 되는지."""
        stats = self._stats.get(symbol)
        if stats is None:
            return True  # 기록 없으면 허용
        return not stats.is_excluded

    def get_excluded(self) -> list[str]:
        """현재 제외된 심볼 목록."""
        return [sym for sym, s in self._stats.items() if s.is_excluded]

    def get_report(self) -> dict:
        """전체 건강도 리포트."""
        report = {}
        for sym, s in self._stats.items():
            if not s.trades:
                continue
            report[sym] = {
                "trades": len(s.trades),
                "win_rate": round(s.win_rate(self.config.lookback_trades), 1),
                "avg_pnl": round(s.avg_pnl(self.config.lookback_trades), 3),
                "consecutive_losses": s.consecutive_losses,
                "is_excluded": s.is_excluded,
            }
        return report

    def _evaluate(self, symbol: str) -> None:
        """건강도 평가 → 제외/복귀 결정."""
        cfg = self.config
        stats = self._stats[symbol]

        if len(stats.trades) < cfg.min_trades_for_eval:
            return

        # 제외 조건: N연패 OR 승률 하한
        if not stats.is_excluded:
            if stats.consecutive_losses >= cfg.max_consecutive_losses:
                stats.is_excluded = True
                stats.excluded_at = datetime.now(timezone.utc).isoformat()
                stats.recovery_count = 0
                logger.warning("[건강도] %s 제외: %d연패", symbol, stats.consecutive_losses)
            elif stats.win_rate(cfg.lookback_trades) < cfg.min_win_rate:
                stats.is_excluded = True
                stats.excluded_at = datetime.now(timezone.utc).isoformat()
                stats.recovery_count = 0
                logger.warning("[건강도] %s 제외: 승률 %.1f%% < %.1f%%",
                             symbol, stats.win_rate(cfg.lookback_trades), cfg.min_win_rate)

        # 복귀 조건: 제외 후 N거래 경과 + 최근 성과 양수
        elif stats.recovery_count >= cfg.recovery_trades:
            recent_pnl = stats.avg_pnl(cfg.recovery_trades)
            if recent_pnl > 0:
                stats.is_excluded = False
                stats.excluded_at = ""
                stats.recovery_count = 0
                logger.info("[건강도] %s 복귀: 최근 %d거래 평균 %+.3f%%",
                          symbol, cfg.recovery_trades, recent_pnl)

    def _save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for sym, s in self._stats.items():
            data[sym] = {
                "trades": s.trades[-50:],
                "consecutive_losses": s.consecutive_losses,
                "is_excluded": s.is_excluded,
                "excluded_at": s.excluded_at,
                "recovery_count": s.recovery_count,
            }
        STATE_PATH.write_text(json.dumps(data, indent=2))

    def _load_state(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            data = json.loads(STATE_PATH.read_text())
            for sym, d in data.items():
                s = SymbolStats(
                    trades=d.get("trades", []),
                    consecutive_losses=d.get("consecutive_losses", 0),
                    is_excluded=d.get("is_excluded", False),
                    excluded_at=d.get("excluded_at", ""),
                    recovery_count=d.get("recovery_count", 0),
                )
                self._stats[sym] = s
        except Exception as e:
            logger.warning("건강도 상태 로드 실패: %s", e)

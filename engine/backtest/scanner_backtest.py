"""롤링윈도우 스캐너 백테스터.

scan_*() 함수를 과거 데이터 위에서 바 단위로 호출하여
실제 스캐너 동작을 시뮬레이션한다.

기존 BacktestRunner는 vectorized 시그널 컬럼 방식이지만,
scan_*()는 DataFrame 입력 → Signal|None 출력 구조이므로
별도 어댑터가 필요하다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from engine.backtest.metrics import (
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_win_rate,
)

logger = logging.getLogger(__name__)

# 수수료: 업비트 편도 0.05% (메이커), 실제 왕복 ~0.1%
COMMISSION_PCT = 0.001  # 왕복 0.1%


@dataclass
class ScannerBacktestConfig:
    """스캐너 백테스트 설정."""
    strategy_fn: Callable
    strategy_name: str
    symbol: str
    interval: str = "5m"
    lookback_bars: int = 100       # 각 스캔 시 사용할 과거 봉 수
    days: int = 30                 # 백테스트 기간
    scanner_config: Any = None     # UpbitScannerConfig 오버라이드
    timeout_bars: int = 50         # SL/TP 미체결 시 강제 청산 봉 수
    commission_pct: float = COMMISSION_PCT


@dataclass
class TradeResult:
    """개별 거래 결과."""
    entry_time: datetime
    entry_price: float
    side: str                      # "LONG" | "SHORT"
    sl: float
    tp1: float
    tp2: float | None
    tp3: float | None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""          # "TP1" | "TP2" | "TP3" | "SL" | "TIMEOUT"
    pnl_pct: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "entry_time": str(self.entry_time),
            "entry_price": self.entry_price,
            "side": self.side,
            "sl": self.sl,
            "tp1": self.tp1,
            "exit_time": str(self.exit_time) if self.exit_time else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl_pct": round(self.pnl_pct, 4),
            "confidence": round(self.confidence, 2),
        }


@dataclass
class BacktestReport:
    """백테스트 결과 리포트."""
    strategy_name: str
    symbol: str
    interval: str
    period: str
    total_trades: int
    win_rate: float
    profit_factor: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_trade_pct: float
    avg_winner_pct: float
    avg_loser_pct: float
    trades: list[TradeResult] = field(default_factory=list)

    def summary_text(self) -> str:
        """Discord embed용 요약 텍스트."""
        pf_str = f"{self.profit_factor:.2f}" if self.profit_factor != float("inf") else "∞"
        return (
            f"**{self.strategy_name}** | {self.symbol} | {self.period}\n"
            f"거래: {self.total_trades} | 승률: {self.win_rate:.1%} | PF: {pf_str}\n"
            f"수익: {self.total_return_pct:+.2f}% | MDD: {self.max_drawdown_pct:.2f}%\n"
            f"Sharpe: {self.sharpe_ratio:.2f}\n"
            f"평균: {self.avg_trade_pct:+.3f}% | W: {self.avg_winner_pct:+.3f}% | L: {self.avg_loser_pct:.3f}%"
        )

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "interval": self.interval,
            "period": self.period,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": self.profit_factor if self.profit_factor != float("inf") else 999.0,
            "total_return_pct": round(self.total_return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio else None,
            "avg_trade_pct": round(self.avg_trade_pct, 4),
            "avg_winner_pct": round(self.avg_winner_pct, 4),
            "avg_loser_pct": round(self.avg_loser_pct, 4),
            "total_trades_list": len(self.trades),
        }


class ScannerBacktester:
    """롤링 윈도우 스캐너 백테스터.

    과거 데이터 위에서 scan_*()를 바 단위로 호출하여
    진입 시그널을 수집하고, SL/TP 기반으로 청산을 시뮬레이션한다.
    """

    def __init__(self, cache_manager: Any) -> None:
        """
        Args:
            cache_manager: OHLCVCacheManager 인스턴스
        """
        self.cache = cache_manager

    async def run(self, config: ScannerBacktestConfig) -> BacktestReport:
        """롤링 윈도우 백테스트 실행.

        Args:
            config: 백테스트 설정

        Returns:
            BacktestReport
        """
        # 과거 데이터 수집
        df = self.cache.fetch_historical(
            config.symbol, config.interval, config.days
        )
        if df is None or len(df) < config.lookback_bars + 10:
            return self._empty_report(config)

        # scanner config 준비
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        scanner_cfg = config.scanner_config or UpbitScannerConfig()

        trades: list[TradeResult] = []
        in_trade = False
        current_trade: TradeResult | None = None

        # 바 단위 순회
        for i in range(config.lookback_bars, len(df)):
            # 기존 포지션 체크 (SL/TP/TIMEOUT)
            if in_trade and current_trade:
                bar = df.iloc[i]
                closed, reason = self._check_exit(
                    current_trade, bar, i, config,
                    entry_bar_idx=i - len(trades) if trades else i,
                )
                if closed:
                    current_trade.exit_time = bar.name
                    current_trade.exit_price = self._get_exit_price(
                        current_trade, bar, reason
                    )
                    current_trade.exit_reason = reason
                    current_trade.pnl_pct = self._calc_pnl(
                        current_trade, config.commission_pct
                    )
                    trades.append(current_trade)
                    in_trade = False
                    current_trade = None
                    continue

            # 새 시그널 탐색 (포지션 없을 때만)
            if not in_trade:
                window = df.iloc[max(0, i - config.lookback_bars):i + 1].copy()
                if len(window) < 30:
                    continue

                try:
                    sig = config.strategy_fn(window, config.symbol, scanner_cfg)
                except TypeError:
                    try:
                        sig = config.strategy_fn(window, config.symbol, scanner_cfg, context={})
                    except Exception:
                        continue
                except Exception:
                    continue

                if sig is None:
                    continue

                # 진입
                entry_bar = df.iloc[i]
                current_trade = TradeResult(
                    entry_time=entry_bar.name,
                    entry_price=float(entry_bar["close"]),
                    side=sig.side,
                    sl=sig.sl,
                    tp1=sig.tp1,
                    tp2=getattr(sig, "tp2", None),
                    tp3=getattr(sig, "tp3", None),
                    confidence=sig.confidence,
                )
                current_trade._entry_bar_idx = i  # 내부 추적용
                in_trade = True

        # 미청산 포지션 → 마지막 봉에서 강제 청산
        if in_trade and current_trade:
            last_bar = df.iloc[-1]
            current_trade.exit_time = last_bar.name
            current_trade.exit_price = float(last_bar["close"])
            current_trade.exit_reason = "TIMEOUT"
            current_trade.pnl_pct = self._calc_pnl(
                current_trade, config.commission_pct
            )
            trades.append(current_trade)

        return self._compile_report(trades, config, df)

    def _check_exit(
        self,
        trade: TradeResult,
        bar: pd.Series,
        bar_idx: int,
        config: ScannerBacktestConfig,
        entry_bar_idx: int,
    ) -> tuple[bool, str]:
        """SL/TP/TIMEOUT 체크."""
        high = float(bar["high"])
        low = float(bar["low"])

        bars_held = bar_idx - getattr(trade, "_entry_bar_idx", bar_idx)

        if trade.side == "LONG":
            # SL hit
            if low <= trade.sl:
                return True, "SL"
            # TP3 hit (최우선)
            if trade.tp3 and high >= trade.tp3:
                return True, "TP3"
            # TP2 hit
            if trade.tp2 and high >= trade.tp2:
                return True, "TP2"
            # TP1 hit
            if high >= trade.tp1:
                return True, "TP1"
        else:  # SHORT
            # SL hit
            if high >= trade.sl:
                return True, "SL"
            # TP3 hit
            if trade.tp3 and low <= trade.tp3:
                return True, "TP3"
            # TP2 hit
            if trade.tp2 and low <= trade.tp2:
                return True, "TP2"
            # TP1 hit
            if low <= trade.tp1:
                return True, "TP1"

        # TIMEOUT
        if bars_held >= config.timeout_bars:
            return True, "TIMEOUT"

        return False, ""

    def _get_exit_price(
        self, trade: TradeResult, bar: pd.Series, reason: str
    ) -> float:
        """청산 가격 결정."""
        if reason == "SL":
            return trade.sl
        elif reason == "TP1":
            return trade.tp1
        elif reason == "TP2":
            return trade.tp2 or trade.tp1
        elif reason == "TP3":
            return trade.tp3 or trade.tp2 or trade.tp1
        else:  # TIMEOUT
            return float(bar["close"])

    def _calc_pnl(self, trade: TradeResult, commission: float) -> float:
        """PnL % 계산 (수수료 포함)."""
        if trade.exit_price is None:
            return 0.0
        if trade.side == "LONG":
            raw = (trade.exit_price - trade.entry_price) / trade.entry_price
        else:
            raw = (trade.entry_price - trade.exit_price) / trade.entry_price
        return raw - commission

    def _compile_report(
        self,
        trades: list[TradeResult],
        config: ScannerBacktestConfig,
        df: pd.DataFrame,
    ) -> BacktestReport:
        """거래 목록 → BacktestReport 생성."""
        if not trades:
            return self._empty_report(config)

        pnls = [t.pnl_pct for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        # 누적 수익률 (복리)
        cum_return = 1.0
        equity = [1.0]
        for p in pnls:
            cum_return *= (1 + p)
            equity.append(cum_return)
        total_return_pct = (cum_return - 1) * 100

        equity_series = pd.Series(equity)
        max_dd = compute_max_drawdown(equity_series)
        sharpe = compute_sharpe_ratio(equity_series, periods_per_year=365 * 24 * 12)  # 5분봉 기준

        period_str = f"{df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}"

        return BacktestReport(
            strategy_name=config.strategy_name,
            symbol=config.symbol,
            interval=config.interval,
            period=period_str,
            total_trades=len(trades),
            win_rate=compute_win_rate(pnls),
            profit_factor=compute_profit_factor(pnls),
            total_return_pct=total_return_pct,
            max_drawdown_pct=abs(max_dd * 100) if max_dd else 0.0,
            sharpe_ratio=sharpe,
            avg_trade_pct=sum(pnls) / len(pnls) * 100 if pnls else 0.0,
            avg_winner_pct=sum(winners) / len(winners) * 100 if winners else 0.0,
            avg_loser_pct=sum(losers) / len(losers) * 100 if losers else 0.0,
            trades=trades,
        )

    def _empty_report(self, config: ScannerBacktestConfig) -> BacktestReport:
        """데이터 부족 시 빈 리포트."""
        return BacktestReport(
            strategy_name=config.strategy_name,
            symbol=config.symbol,
            interval=config.interval,
            period="N/A",
            total_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=None,
            avg_trade_pct=0.0,
            avg_winner_pct=0.0,
            avg_loser_pct=0.0,
        )

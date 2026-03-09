"""스캐너 전략 파라미터 그리드 최적화.

scan_*() 함수의 파라미터를 그리드 서치로 탐색하여
최적 조합을 찾는다. 과적합 방지를 위해 train/test 분리.
"""

from __future__ import annotations

import copy
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.backtest.scanner_backtest import (
    BacktestReport,
    ScannerBacktestConfig,
    ScannerBacktester,
)

logger = logging.getLogger(__name__)

# 최소 거래 수: 이 이하면 통계적으로 무의미
MIN_TRADES = 10


@dataclass
class ParamRange:
    """최적화 대상 파라미터 범위."""
    name: str          # config 필드명 (e.g. "rsi_period", "ema_fast")
    values: list       # 탐색 값 목록 (e.g. [10, 14, 20])


@dataclass
class OptimizeResult:
    """최적화 결과."""
    best_params: dict
    best_sharpe: float
    best_win_rate: float
    best_profit_factor: float
    best_report: BacktestReport | None = None
    # Train/Test 분리 결과
    test_sharpe: float | None = None
    test_win_rate: float | None = None
    test_profit_factor: float | None = None
    test_report: BacktestReport | None = None
    grid_results: list[dict] = field(default_factory=list)

    def summary_text(self) -> str:
        """Discord embed용 요약."""
        pf = f"{self.best_profit_factor:.2f}" if self.best_profit_factor != float("inf") else "∞"
        lines = [
            f"**최적 파라미터**: {self.best_params}",
            f"**Train** — Sharpe: {self.best_sharpe:.2f} | 승률: {self.best_win_rate:.1%} | PF: {pf}",
        ]
        if self.test_sharpe is not None:
            test_pf = f"{self.test_profit_factor:.2f}" if self.test_profit_factor and self.test_profit_factor != float("inf") else "N/A"
            lines.append(
                f"**Test** — Sharpe: {self.test_sharpe:.2f} | 승률: {self.test_win_rate:.1%} | PF: {test_pf}"
            )
        lines.append(f"총 {len(self.grid_results)}개 조합 탐색")
        return "\n".join(lines)


class ScannerOptimizer:
    """스캐너 전략 파라미터 그리드 최적화.

    train/test 분리 (70/30)로 과적합 방지.
    Sharpe ratio 기준 정렬 (단순 수익률 아닌 위험조정 수익).
    """

    def __init__(self, backtester: ScannerBacktester) -> None:
        self.backtester = backtester

    async def grid_search(
        self,
        strategy_fn: Callable,
        strategy_name: str,
        symbol: str,
        param_ranges: list[ParamRange],
        days: int = 30,
        interval: str = "5m",
        metric: str = "sharpe",
        min_trades: int = MIN_TRADES,
        train_ratio: float = 0.7,
    ) -> OptimizeResult:
        """그리드 서치로 최적 파라미터 탐색.

        Args:
            strategy_fn: scan_*() 함수
            strategy_name: 전략 이름
            symbol: 심볼
            param_ranges: 파라미터 범위 목록
            days: 총 백테스트 기간
            interval: 타임프레임
            metric: 최적화 기준 ("sharpe" | "win_rate" | "profit_factor")
            min_trades: 최소 거래 수 (이하는 무효)
            train_ratio: 학습 데이터 비율 (과적합 방지)

        Returns:
            OptimizeResult
        """
        from engine.strategy.upbit_scanner import UpbitScannerConfig

        # 파라미터 조합 생성
        param_names = [p.name for p in param_ranges]
        param_values = [p.values for p in param_ranges]
        combinations = list(itertools.product(*param_values))

        logger.info(
            "Grid search: %s %s — %d combinations",
            strategy_name, symbol, len(combinations),
        )

        # Train/Test 기간 분리
        train_days = int(days * train_ratio)
        test_days = days - train_days

        grid_results: list[dict] = []
        best_metric_val = float("-inf")
        best_params: dict = {}
        best_report: BacktestReport | None = None

        for combo in combinations:
            params = dict(zip(param_names, combo))

            # Config에 파라미터 적용
            cfg = UpbitScannerConfig()
            for name, val in params.items():
                if hasattr(cfg, name):
                    setattr(cfg, name, val)

            # Train 기간 백테스트
            bt_config = ScannerBacktestConfig(
                strategy_fn=strategy_fn,
                strategy_name=strategy_name,
                symbol=symbol,
                interval=interval,
                days=train_days,
                scanner_config=cfg,
            )

            try:
                report = await self.backtester.run(bt_config)
            except Exception as e:
                logger.debug("Grid search error for %s: %s", params, e)
                continue

            # 최소 거래 수 필터
            if report.total_trades < min_trades:
                continue

            # 메트릭 추출
            if metric == "sharpe":
                val = report.sharpe_ratio or float("-inf")
            elif metric == "win_rate":
                val = report.win_rate
            elif metric == "profit_factor":
                val = report.profit_factor if report.profit_factor != float("inf") else 999.0
            else:
                val = report.sharpe_ratio or float("-inf")

            result_entry = {
                "params": params,
                "sharpe": report.sharpe_ratio,
                "win_rate": report.win_rate,
                "profit_factor": report.profit_factor,
                "total_return_pct": report.total_return_pct,
                "total_trades": report.total_trades,
                "max_drawdown_pct": report.max_drawdown_pct,
            }
            grid_results.append(result_entry)

            if val > best_metric_val:
                best_metric_val = val
                best_params = params
                best_report = report

        if not best_params:
            return OptimizeResult(
                best_params={},
                best_sharpe=0.0,
                best_win_rate=0.0,
                best_profit_factor=0.0,
                grid_results=grid_results,
            )

        # Test 기간 검증 (과적합 확인)
        test_report: BacktestReport | None = None
        test_sharpe = None
        test_win_rate = None
        test_profit_factor = None

        if test_days >= 7:
            test_cfg = UpbitScannerConfig()
            for name, val in best_params.items():
                if hasattr(test_cfg, name):
                    setattr(test_cfg, name, val)

            test_bt_config = ScannerBacktestConfig(
                strategy_fn=strategy_fn,
                strategy_name=strategy_name,
                symbol=symbol,
                interval=interval,
                days=test_days,
                scanner_config=test_cfg,
            )

            try:
                test_report = await self.backtester.run(test_bt_config)
                test_sharpe = test_report.sharpe_ratio
                test_win_rate = test_report.win_rate
                test_profit_factor = test_report.profit_factor
            except Exception as e:
                logger.warning("Test period backtest failed: %s", e)

        # 결과 정렬 (메트릭 기준 내림차순)
        sort_key = metric if metric in ("sharpe", "win_rate", "profit_factor") else "sharpe"
        grid_results.sort(
            key=lambda r: r.get(sort_key) or float("-inf"),
            reverse=True,
        )

        return OptimizeResult(
            best_params=best_params,
            best_sharpe=best_report.sharpe_ratio or 0.0 if best_report else 0.0,
            best_win_rate=best_report.win_rate if best_report else 0.0,
            best_profit_factor=best_report.profit_factor if best_report else 0.0,
            best_report=best_report,
            test_sharpe=test_sharpe,
            test_win_rate=test_win_rate,
            test_profit_factor=test_profit_factor,
            test_report=test_report,
            grid_results=grid_results,
        )


# 전략별 기본 파라미터 범위 정의
# 각 전략의 핵심 지표 파라미터 + SL/TP를 포함
DEFAULT_PARAM_RANGES: dict[str, list[ParamRange]] = {
    "EMA+RSI+VWAP": [
        ParamRange("ema_fast", [7, 9, 12]),
        ParamRange("ema_slow", [18, 21, 26]),
        ParamRange("rsi_period", [10, 14, 20]),
    ],
    "Supertrend": [
        ParamRange("supertrend_period", [7, 10, 14]),
        ParamRange("supertrend_multiplier", [2.0, 3.0, 4.0]),
        ParamRange("sl_pct", [0.008, 0.01, 0.015]),
    ],
    "MACD Divergence": [
        ParamRange("macd_fast", [8, 12, 16]),
        ParamRange("macd_slow", [21, 26, 30]),
        ParamRange("macd_signal", [7, 9, 12]),
    ],
    "StochRSI": [
        ParamRange("stoch_period", [10, 14, 20]),
        ParamRange("stoch_k", [3, 5]),
        ParamRange("stoch_d", [3, 5]),
        ParamRange("sl_pct", [0.008, 0.01, 0.015]),
    ],
    "Fibonacci": [
        ParamRange("ema_fast", [7, 9, 12]),
        ParamRange("ema_slow", [18, 21, 26]),
        ParamRange("rsi_period", [10, 14, 20]),
    ],
    "Ichimoku": [
        ParamRange("ichimoku_tenkan", [7, 9, 12]),
        ParamRange("ichimoku_kijun", [22, 26, 30]),
        ParamRange("ichimoku_senkou", [44, 52, 60]),
    ],
    "Early Pump": [
        ParamRange("vol_mult", [1.2, 1.5, 2.0]),
        ParamRange("sl_pct", [0.008, 0.01, 0.015]),
    ],
    "SMC": [
        ParamRange("rsi_period", [10, 14, 20]),
        ParamRange("atr_period", [10, 14, 20]),
        ParamRange("sl_pct", [0.008, 0.01, 0.015]),
    ],
    "Hidden Div": [
        ParamRange("rsi_period", [10, 14, 20]),
        ParamRange("sl_pct", [0.008, 0.01, 0.015]),
    ],
    "BB+RSI+Stoch": [
        ParamRange("rsi_period", [10, 14, 20]),
        ParamRange("bb_period", [15, 20, 25]),
        ParamRange("stoch_period", [10, 14, 20]),
    ],
}

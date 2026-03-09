from __future__ import annotations

from engine.backtest.metrics import (
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_total_return,
    compute_win_rate,
)
from engine.backtest.optimizer import GridOptimizer, OptimizationResult
from engine.backtest.report import generate_report, generate_summary
from engine.backtest.runner import BacktestResult, BacktestRunner, TradeRecord
from engine.backtest.scanner_backtest import (
    BacktestReport,
    ScannerBacktestConfig,
    ScannerBacktester,
    TradeResult,
)
from engine.backtest.scanner_optimizer import (
    OptimizeResult,
    ParamRange,
    ScannerOptimizer,
)
from engine.backtest.auto_reoptimize import (
    ReoptimizeScheduler,
    reoptimize_symbol,
)

__all__ = [
    "BacktestRunner",
    "BacktestResult",
    "TradeRecord",
    "compute_total_return",
    "compute_sharpe_ratio",
    "compute_max_drawdown",
    "compute_win_rate",
    "compute_profit_factor",
    "generate_report",
    "generate_summary",
    "GridOptimizer",
    "OptimizationResult",
    # Scanner backtest
    "ScannerBacktester",
    "ScannerBacktestConfig",
    "BacktestReport",
    "TradeResult",
    # Scanner optimizer
    "ScannerOptimizer",
    "OptimizeResult",
    "ParamRange",
    # Auto re-optimization
    "ReoptimizeScheduler",
    "reoptimize_symbol",
]

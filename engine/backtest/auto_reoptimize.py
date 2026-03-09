"""자동 주기적 재최적화 스케줄러.

주 1회 (또는 수동 트리거) 최근 데이터 기반으로
각 전략의 최적 파라미터를 탐색하고 config에 적용한다.

Walk-forward optimization: 최근 N일 데이터로 학습 → 검증 → 적용.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OPTIMIZED_PARAMS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "optimized_params.json"

# 최적화 대상 전략 → scan 함수 매핑 (lazy import)
STRATEGY_MAP = {
    "EMA+RSI+VWAP": "scan_ema_rsi_vwap",
    "Supertrend": "scan_supertrend",
    "MACD Divergence": "scan_macd_divergence",
    "StochRSI": "scan_stoch_rsi",
    "Fibonacci": "scan_fibonacci",
    "Ichimoku": "scan_ichimoku",
    "Early Pump": "scan_early_pump",
    "SMC": "scan_smc",
    "Hidden Div": "scan_hidden_divergence",
    "BB+RSI+Stoch": "scan_bb_rsi_stoch",
}


def _get_scan_fn(fn_name: str):
    """Lazy import scan function."""
    import engine.strategy.upbit_scanner as scanner
    return getattr(scanner, fn_name)


def load_optimized_params() -> dict:
    """저장된 최적화 결과 로드."""
    if OPTIMIZED_PARAMS_PATH.exists():
        try:
            return json.loads(OPTIMIZED_PARAMS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_optimized_params(data: dict) -> None:
    """최적화 결과 저장."""
    OPTIMIZED_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPTIMIZED_PARAMS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str)
    )


async def reoptimize_symbol(
    symbol: str,
    strategies: list[str] | None = None,
    days: int = 30,
    apply_to_config: bool = True,
) -> dict[str, Any]:
    """특정 심볼에 대해 전략 파라미터 재최적화 실행.

    Args:
        symbol: 심볼 (e.g. "KRW-BTC")
        strategies: 최적화할 전략 목록 (None이면 전체)
        days: 최적화 기간
        apply_to_config: True면 최적 파라미터를 scanner config에 즉시 적용

    Returns:
        {strategy_name: {params, sharpe, win_rate, profit_factor, ...}}
    """
    from engine.data.upbit_cache import OHLCVCacheManager
    from engine.backtest.scanner_backtest import ScannerBacktester
    from engine.backtest.scanner_optimizer import ScannerOptimizer, DEFAULT_PARAM_RANGES

    cache = OHLCVCacheManager()
    backtester = ScannerBacktester(cache)
    optimizer = ScannerOptimizer(backtester)

    target_strategies = strategies or list(STRATEGY_MAP.keys())
    results = {}

    for strat_name in target_strategies:
        fn_name = STRATEGY_MAP.get(strat_name)
        if not fn_name:
            continue

        param_ranges = DEFAULT_PARAM_RANGES.get(strat_name)
        if not param_ranges:
            continue

        scan_fn = _get_scan_fn(fn_name)

        try:
            result = await optimizer.grid_search(
                strategy_fn=scan_fn,
                strategy_name=strat_name,
                symbol=symbol,
                param_ranges=param_ranges,
                days=days,
            )

            if result.best_params:
                results[strat_name] = {
                    "params": result.best_params,
                    "train_sharpe": result.best_sharpe,
                    "train_win_rate": result.best_win_rate,
                    "train_pf": result.best_profit_factor,
                    "test_sharpe": result.test_sharpe,
                    "test_win_rate": result.test_win_rate,
                    "test_pf": result.test_profit_factor,
                    "combinations_tested": len(result.grid_results),
                }

                logger.info(
                    "Reoptimize %s/%s: %s → Sharpe=%.2f, WR=%.1f%%",
                    symbol, strat_name, result.best_params,
                    result.best_sharpe, result.best_win_rate * 100,
                )

        except Exception as e:
            logger.warning("Reoptimize failed %s/%s: %s", symbol, strat_name, e)

    # 결과 저장
    if results:
        saved = load_optimized_params()
        saved[symbol] = {
            "updated_at": datetime.now().isoformat(),
            "days": days,
            "strategies": results,
        }
        save_optimized_params(saved)

        # Config에 즉시 적용 (모든 전략의 공통 파라미터를 최다 빈도 값으로)
        if apply_to_config:
            _apply_best_params(results)

    return results


def _apply_best_params(results: dict) -> None:
    """최적화 결과를 scanner config에 적용.

    여러 전략의 결과에서 공통 파라미터(rsi_period 등)가 다를 수 있으므로,
    Sharpe 기준 상위 전략의 값을 우선 적용한다.
    """
    from engine.strategy.upbit_scanner import update_config

    # Sharpe 기준 정렬하여 가장 좋은 전략의 파라미터부터 적용
    sorted_results = sorted(
        results.items(),
        key=lambda x: x[1].get("train_sharpe", 0),
        reverse=True,
    )

    params_to_apply = {}
    for strat_name, data in sorted_results:
        for key, val in data.get("params", {}).items():
            # 이미 설정된 파라미터는 건너뜀 (상위 전략 우선)
            if key not in params_to_apply:
                params_to_apply[key] = val

    if params_to_apply:
        update_config(params_to_apply)
        logger.info("Applied optimized params to config: %s", params_to_apply)


class ReoptimizeScheduler:
    """주기적 재최적화 스케줄러.

    기본: 주 1회 (604800초), 설정된 심볼들에 대해 자동 실행.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        interval_sec: int = 604800,  # 1주
        days: int = 30,
    ) -> None:
        self.symbols = symbols or ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
        self.interval_sec = interval_sec
        self.days = days
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_run: float = 0.0

    async def _loop(self) -> None:
        """스케줄러 메인 루프."""
        while self._running:
            try:
                logger.info("Auto-reoptimize starting for %d symbols...", len(self.symbols))
                all_results = {}

                for symbol in self.symbols:
                    results = await reoptimize_symbol(
                        symbol, days=self.days, apply_to_config=True,
                    )
                    all_results[symbol] = results

                self._last_run = time.time()
                total = sum(len(v) for v in all_results.values())
                logger.info("Auto-reoptimize complete: %d strategy/symbol combinations", total)

            except Exception as e:
                logger.error("Auto-reoptimize error: %s", e)

            # 다음 실행까지 대기
            await asyncio.sleep(self.interval_sec)

    def start(self) -> None:
        """스케줄러 시작."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info("Reoptimize scheduler started (interval=%ds)", self.interval_sec)

    def stop(self) -> None:
        """스케줄러 정지."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Reoptimize scheduler stopped")

    def status(self) -> dict:
        """스케줄러 상태."""
        return {
            "running": self._running,
            "symbols": self.symbols,
            "interval_sec": self.interval_sec,
            "days": self.days,
            "last_run": datetime.fromtimestamp(self._last_run).isoformat() if self._last_run else None,
        }

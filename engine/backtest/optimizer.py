"""Grid search optimizer for strategy hyperparameters."""

import copy
import itertools
from dataclasses import dataclass

from engine.backtest.runner import BacktestResult, BacktestRunner
from engine.schema import StrategyDefinition

@dataclass
class OptimizationResult:
    params: dict
    backtest_result: BacktestResult

    @property
    def sharpe(self) -> float:
        return self.backtest_result.sharpe_ratio or float("-inf")

def _set_nested(obj: dict, path: str, value: object) -> dict:
    """Set a value at a dot-separated path in a nested dict/list structure.

    Example path: "indicators.0.params.timeperiod"
    """
    parts = path.split(".")
    node = obj
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return obj

class GridOptimizer:
    """Exhaustive grid search over strategy parameter combinations."""

    def __init__(self) -> None:
        self._runner = BacktestRunner()

    def optimize(
        self,
        strategy: StrategyDefinition,
        symbol: str,
        start: str,
        end: str,
        param_grid: dict[str, list],
        initial_capital: float = 100_000.0,
    ) -> list[OptimizationResult]:
        """Run all combinations of param_grid and return sorted results.

        Args:
            strategy: Base strategy definition to mutate per combination.
            symbol: Ticker symbol.
            start: ISO start date.
            end: ISO end date.
            param_grid: Mapping of dot-path -> list of values.
                Example: {"indicators.0.params.timeperiod": [10, 14, 20]}
            initial_capital: Starting capital for each run.

        Returns:
            List of OptimizationResult sorted descending by sharpe_ratio.
        """
        keys = list(param_grid.keys())
        value_lists = [param_grid[k] for k in keys]
        results: list[OptimizationResult] = []

        for combination in itertools.product(*value_lists):
            params = dict(zip(keys, combination))
            base_dict = strategy.model_dump()
            for path, val in params.items():
                _set_nested(base_dict, path, val)

            candidate = StrategyDefinition.model_validate(base_dict)
            try:
                bt_result = self._runner.run(candidate, symbol, start, end, initial_capital=initial_capital)
                results.append(OptimizationResult(params=copy.deepcopy(params), backtest_result=bt_result))
            except Exception:
                continue

        results.sort(key=lambda r: r.sharpe, reverse=True)
        return results

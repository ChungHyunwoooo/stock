"""Strategy engine that generates trading signals from a StrategyDefinition."""

from __future__ import annotations

import pandas as pd

from engine.indicators.compute import compute_all_indicators
from engine.schema import StrategyDefinition
from engine.strategy.condition import evaluate_condition_group
from engine.strategy.risk import apply_risk_management


class StrategyEngine:
    """Stateless engine that applies a strategy definition to OHLCV data."""

    def __init__(self) -> None:
        pass

    def generate_signals(self, strategy: StrategyDefinition, df: pd.DataFrame) -> pd.DataFrame:
        """Compute indicators, evaluate conditions, and produce signal column.

        Signal values:
            1  = entry
           -1  = exit
            0  = hold

        Args:
            strategy: Full strategy definition.
            df: OHLCV DataFrame with lowercase column names.

        Returns:
            Enriched DataFrame with indicator columns and a 'signal' column.
        """
        df = compute_all_indicators(df, strategy.indicators)

        entry_signals: pd.Series = evaluate_condition_group(df, strategy.entry)
        exit_signals: pd.Series = evaluate_condition_group(df, strategy.exit)

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[entry_signals] = 1
        signal[exit_signals] = -1

        df = df.copy()
        df["signal"] = signal

        df = apply_risk_management(df, strategy.risk, direction=strategy.direction.value)

        return df

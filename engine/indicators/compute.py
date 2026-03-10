"""Compute technical indicators on a DataFrame using ta-lib."""

import pandas as pd

from engine.indicators.registry import get_indicator
from engine.schema import IndicatorDef

def compute_indicator(df: pd.DataFrame, indicator_def: IndicatorDef) -> pd.DataFrame:
    """Compute a single indicator and add result columns to df.

    Handles both single-output (str) and multi-output (dict) IndicatorDef.output.

    Args:
        df: OHLCV DataFrame with lowercase column names.
        indicator_def: Indicator definition including name, params, and output aliases.

    Returns:
        DataFrame with new indicator columns appended.
    """
    fn = get_indicator(indicator_def.name)
    # talib: timeperiod/period 계열은 int, nbdev/acceleration 등은 float 필요
    _FLOAT_PARAMS = {"nbdevup", "nbdevdn", "nbdev", "acceleration", "maximum",
                     "penetration", "startvalue", "offsetonreverse", "accelerationinitlong",
                     "accelerationlong", "accelerationmaxlong", "accelerationinitshort",
                     "accelerationshort", "accelerationmaxshort", "fastk_period", "fastd_period",
                     "slowk_period", "slowd_period"}
    params = {}
    for k, v in indicator_def.params.items():
        if isinstance(v, int) and k.lower() in _FLOAT_PARAMS:
            params[k] = float(v)
        else:
            params[k] = v
    result = fn(df, **params)

    output = indicator_def.output
    if isinstance(output, str):
        # Single-output: result is a Series
        df = df.copy()
        df[output] = result
    else:
        # Multi-output: result is a dict-like object (DataFrame or named outputs)
        df = df.copy()
        if isinstance(result, pd.DataFrame):
            for talib_name, alias in output.items():
                df[alias] = result[talib_name]
        else:
            # talib abstract returns ordered outputs; result may be a list of Series
            # Access by attribute name from the abstract function
            for talib_name, alias in output.items():
                df[alias] = result[talib_name]

    return df

def compute_all_indicators(df: pd.DataFrame, indicators: list[IndicatorDef]) -> pd.DataFrame:
    """Compute all indicators sequentially and return enriched DataFrame."""
    for ind in indicators:
        df = compute_indicator(df, ind)
    return df

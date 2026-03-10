"""TA-Lib indicator registry mapping uppercase names to abstract functions."""

from collections.abc import Callable

import talib.abstract as ta

from engine.indicators.custom import staircase_indicator, watermelon_indicator

INDICATOR_REGISTRY: dict[str, Callable] = {
    "RSI": ta.RSI,
    "MACD": ta.MACD,
    "BBANDS": ta.BBANDS,
    "EMA": ta.EMA,
    "SMA": ta.SMA,
    "STOCH": ta.STOCH,
    "ATR": ta.ATR,
    "ADX": ta.ADX,
    "CCI": ta.CCI,
    "OBV": ta.OBV,
    "WILLR": ta.WILLR,
    "MFI": ta.MFI,
    "DEMA": ta.DEMA,
    "TEMA": ta.TEMA,
    "SAR": ta.SAR,
    "PLUS_DI": ta.PLUS_DI,
    "MINUS_DI": ta.MINUS_DI,
    # Custom composite indicators
    "STAIRCASE": staircase_indicator,
    "WATERMELON": watermelon_indicator,
}

def get_indicator(name: str) -> Callable:
    """Return the ta-lib abstract function for the given uppercase indicator name.

    Raises:
        KeyError: If the indicator is not registered.
    """
    key = name.upper()
    if key not in INDICATOR_REGISTRY:
        raise KeyError(f"Indicator '{name}' is not registered. Available: {sorted(INDICATOR_REGISTRY)}")
    return INDICATOR_REGISTRY[key]

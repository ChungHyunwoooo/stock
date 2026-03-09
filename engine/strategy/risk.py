"""Risk management calculations for position sizing and stop/take-profit levels."""

from __future__ import annotations

import pandas as pd

from engine.schema import RiskParams


def calculate_position_size(
    capital: float,
    risk_params: RiskParams,
    entry_price: float,
    stop_price: float,
) -> float:
    """Calculate number of shares based on risk per trade.

    Args:
        capital: Total available capital.
        risk_params: Risk configuration.
        entry_price: Price at which position is entered.
        stop_price: Stop-loss price level.

    Returns:
        Number of shares (float).
    """
    risk_amount = capital * risk_params.risk_per_trade_pct
    price_diff = abs(entry_price - stop_price)
    if price_diff == 0:
        return 0.0
    return risk_amount / price_diff


def apply_risk_management(
    df: pd.DataFrame,
    risk_params: RiskParams,
    direction: str = "long",
) -> pd.DataFrame:
    """Add stop_loss_price and take_profit_price columns to signal rows.

    Columns are computed relative to the close price at each bar.
    Direction determines which side the SL/TP are placed.
    Non-entry rows (signal != 1) will have NaN values.

    Args:
        df: DataFrame with 'close' and optionally 'signal' columns.
        risk_params: Risk configuration with stop_loss_pct and take_profit_pct.
        direction: "long", "short", or "both" (both defaults to long).

    Returns:
        DataFrame with stop_loss_price and take_profit_price columns added.
    """
    df = df.copy()

    is_short = direction == "short"
    # SL: long이면 아래, short이면 위
    sl_mult = (1 + risk_params.stop_loss_pct) if is_short else (1 - risk_params.stop_loss_pct) if risk_params.stop_loss_pct is not None else None
    # TP: long이면 위, short이면 아래
    tp_mult = (1 - risk_params.take_profit_pct) if is_short else (1 + risk_params.take_profit_pct) if risk_params.take_profit_pct is not None else None

    # entry(signal=1) 행만 SL/TP 계산
    has_signal = "signal" in df.columns
    entry_mask = df["signal"] == 1 if has_signal else pd.Series(True, index=df.index)

    df["stop_loss_price"] = float("nan")
    df["take_profit_price"] = float("nan")

    if sl_mult is not None:
        df.loc[entry_mask, "stop_loss_price"] = df.loc[entry_mask, "close"] * sl_mult

    if tp_mult is not None:
        df.loc[entry_mask, "take_profit_price"] = df.loc[entry_mask, "close"] * tp_mult

    return df

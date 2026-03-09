"""Condition evaluation for strategy entry/exit logic."""

from __future__ import annotations

import functools

import pandas as pd

from engine.schema import Condition, ConditionGroup, ConditionOp


def evaluate_condition(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """Evaluate a single condition against the DataFrame.

    Args:
        df: DataFrame containing indicator and price columns.
        cond: Condition with left column, operator, and right (numeric or column name).

    Returns:
        Boolean Series.
    """
    left = df[cond.left]
    op = cond.op
    right = cond.right

    # Determine whether right side is a column reference or numeric literal
    right_is_col = isinstance(right, str)
    right_series = df[right] if right_is_col else right

    if op == ConditionOp.gt:
        return left > right_series
    elif op == ConditionOp.gte:
        return left >= right_series
    elif op == ConditionOp.lt:
        return left < right_series
    elif op == ConditionOp.lte:
        return left <= right_series
    elif op == ConditionOp.eq:
        return left == right_series
    elif op == ConditionOp.crosses_above:
        if right_is_col:
            prev_left = left.shift(1)
            prev_right = right_series.shift(1)
            return ((prev_left <= prev_right) & (left > right_series)).rename(cond.left)
        else:
            return (left.shift(1) <= right_series) & (left > right_series)
    elif op == ConditionOp.crosses_below:
        if right_is_col:
            prev_left = left.shift(1)
            prev_right = right_series.shift(1)
            return ((prev_left >= prev_right) & (left < right_series)).rename(cond.left)
        else:
            return (left.shift(1) >= right_series) & (left < right_series)
    else:
        raise ValueError(f"Unknown operator: {op}")


def evaluate_condition_group(df: pd.DataFrame, group: ConditionGroup) -> pd.Series:
    """Evaluate a group of conditions combined with AND or OR logic.

    Args:
        df: DataFrame containing indicator and price columns.
        group: ConditionGroup with logic ("and"/"or") and list of conditions.

    Returns:
        Boolean Series.
    """
    series_list = [evaluate_condition(df, cond) for cond in group.conditions]

    if group.logic == "and":
        return functools.reduce(lambda a, b: a & b, series_list)
    else:  # "or"
        return functools.reduce(lambda a, b: a | b, series_list)

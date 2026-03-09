"""Tests for engine/strategy/condition.py — condition evaluation logic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.schema import Condition, ConditionGroup, ConditionOp
from engine.strategy.condition import evaluate_condition, evaluate_condition_group


@pytest.fixture
def df() -> pd.DataFrame:
    """DataFrame with known values for deterministic condition testing.

    col_a: [10, 25, 35, 40, 35, 25, 15]
    col_b: [30, 30, 30, 30, 30, 30, 30]  (constant threshold column)
    """
    idx = pd.date_range("2024-01-01", periods=7, freq="D")
    return pd.DataFrame(
        {
            "col_a": [10.0, 25.0, 35.0, 40.0, 35.0, 25.0, 15.0],
            "col_b": [30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0],
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# crosses_above
# ---------------------------------------------------------------------------

def test_crosses_above_numeric(df):
    """col_a crosses above 30 when it moves from <=30 to >30 (index 2)."""
    cond = Condition(left="col_a", op=ConditionOp.crosses_above, right=30)
    result = evaluate_condition(df, cond)

    assert result.dtype == bool or result.dtype == object or result.dtype == np.bool_
    # Index 2: prev=25 <=30, cur=35 >30  => True
    assert result.iloc[2] is True or result.iloc[2] == True
    # Index 0: no previous row (NaN shift) => False
    assert not result.iloc[0]
    # Index 3: prev=35 > 30, not a cross => False
    assert not result.iloc[3]


def test_crosses_below_numeric(df):
    """col_a crosses below 30 when it moves from >=30 to <30 (index 5)."""
    cond = Condition(left="col_a", op=ConditionOp.crosses_below, right=30)
    result = evaluate_condition(df, cond)

    # Index 5: prev=35 >=30, cur=25 <30 => True
    assert result.iloc[5] is True or result.iloc[5] == True
    # Index 2: col_a goes above 30, not below => False
    assert not result.iloc[2]


def test_crosses_above_column(df):
    """col_a crosses above col_b (also 30) — should match numeric variant."""
    cond_col = Condition(left="col_a", op=ConditionOp.crosses_above, right="col_b")
    cond_num = Condition(left="col_a", op=ConditionOp.crosses_above, right=30)

    result_col = evaluate_condition(df, cond_col)
    result_num = evaluate_condition(df, cond_num)

    pd.testing.assert_series_equal(result_col.astype(bool), result_num.astype(bool), check_names=False)


# ---------------------------------------------------------------------------
# gt / lt / gte / lte / eq
# ---------------------------------------------------------------------------

def test_gt_comparison(df):
    cond = Condition(left="col_a", op=ConditionOp.gt, right=30)
    result = evaluate_condition(df, cond)
    expected = df["col_a"] > 30
    pd.testing.assert_series_equal(result, expected)


def test_lt_comparison(df):
    cond = Condition(left="col_a", op=ConditionOp.lt, right=30)
    result = evaluate_condition(df, cond)
    expected = df["col_a"] < 30
    pd.testing.assert_series_equal(result, expected)


def test_gte_comparison(df):
    cond = Condition(left="col_a", op=ConditionOp.gte, right=35)
    result = evaluate_condition(df, cond)
    expected = df["col_a"] >= 35
    pd.testing.assert_series_equal(result, expected)


def test_lte_comparison(df):
    cond = Condition(left="col_a", op=ConditionOp.lte, right=25)
    result = evaluate_condition(df, cond)
    expected = df["col_a"] <= 25
    pd.testing.assert_series_equal(result, expected)


def test_eq_comparison(df):
    cond = Condition(left="col_a", op=ConditionOp.eq, right=40.0)
    result = evaluate_condition(df, cond)
    expected = df["col_a"] == 40.0
    pd.testing.assert_series_equal(result, expected)
    assert result.iloc[3]  # only index 3 equals 40


# ---------------------------------------------------------------------------
# ConditionGroup AND / OR
# ---------------------------------------------------------------------------

def test_condition_group_and(df):
    """AND: col_a > 30 AND col_a < 40 — only indices 2 and 4 (35.0)."""
    group = ConditionGroup(
        logic="and",
        conditions=[
            Condition(left="col_a", op=ConditionOp.gt, right=30),
            Condition(left="col_a", op=ConditionOp.lt, right=40),
        ],
    )
    result = evaluate_condition_group(df, group)
    expected = (df["col_a"] > 30) & (df["col_a"] < 40)
    pd.testing.assert_series_equal(result, expected)
    # Indices 2 and 4 have col_a=35 which is >30 and <40
    assert result.iloc[2]
    assert result.iloc[4]
    assert not result.iloc[3]  # 40 is not <40


def test_condition_group_or(df):
    """OR: col_a < 15 OR col_a > 38 — only indices 0 and 3."""
    group = ConditionGroup(
        logic="or",
        conditions=[
            Condition(left="col_a", op=ConditionOp.lt, right=15),
            Condition(left="col_a", op=ConditionOp.gt, right=38),
        ],
    )
    result = evaluate_condition_group(df, group)
    expected = (df["col_a"] < 15) | (df["col_a"] > 38)
    pd.testing.assert_series_equal(result, expected)
    assert result.iloc[0]       # 10 < 15 => True
    assert result.iloc[3]       # 40 > 38 => True
    assert not result.iloc[6]   # 15 is not <15 and not >38 => False

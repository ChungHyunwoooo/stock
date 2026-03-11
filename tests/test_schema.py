"""Tests for engine/schema.py — StrategyDefinition validation and serialization."""

import json
import pathlib

import pytest
from pydantic import ValidationError

from engine.schema import (
    Condition,
    ConditionGroup,
    ConditionOp,
    Direction,
    IndicatorDef,
    MarketType,
    RiskParams,
    StrategyDefinition,
    StrategyStatus,
)

STRATEGIES_DIR = pathlib.Path(__file__).parent.parent / "strategies"

def test_valid_strategy_from_json():
    """Load rsi_macd_momentum definition.json and parse with StrategyDefinition."""
    json_path = STRATEGIES_DIR / "rsi_macd_momentum" / "definition.json"
    assert json_path.exists(), f"Strategy file not found: {json_path}"

    raw = json_path.read_text(encoding="utf-8")
    strategy = StrategyDefinition.model_validate_json(raw)

    assert strategy.name == "RSI + MACD Momentum"
    assert strategy.version == "1.0"
    assert strategy.status == StrategyStatus.testing
    assert MarketType.us_stock in strategy.markets
    assert MarketType.crypto_spot in strategy.markets
    assert strategy.direction == Direction.long
    assert len(strategy.indicators) == 2
    assert len(strategy.entry.conditions) == 2
    assert len(strategy.exit.conditions) == 2
    assert strategy.risk.stop_loss_pct == pytest.approx(0.03)
    assert strategy.risk.take_profit_pct == pytest.approx(0.09)

def test_invalid_strategy_missing_fields():
    """Validation should fail when required fields are absent."""
    # Missing 'markets' and 'indicators' — both are required with min_length=1
    with pytest.raises(ValidationError) as exc_info:
        StrategyDefinition.model_validate(
            {
                "name": "Broken Strategy",
                "entry": {"conditions": [{"left": "rsi", "op": "gt", "right": 30}]},
                "exit": {"conditions": [{"left": "rsi", "op": "lt", "right": 70}]},
            }
        )
    errors = exc_info.value.errors()
    field_names = {e["loc"][0] for e in errors}
    assert "markets" in field_names or "indicators" in field_names

def test_strategy_serialization_roundtrip(sample_strategy):
    """model_dump_json -> model_validate_json should preserve all fields."""
    json_str = sample_strategy.model_dump_json()
    restored = StrategyDefinition.model_validate_json(json_str)

    assert restored.name == sample_strategy.name
    assert restored.status == sample_strategy.status
    assert restored.markets == sample_strategy.markets
    assert len(restored.indicators) == len(sample_strategy.indicators)
    assert restored.indicators[0].name == sample_strategy.indicators[0].name
    assert restored.risk.stop_loss_pct == sample_strategy.risk.stop_loss_pct
    assert restored.risk.take_profit_pct == sample_strategy.risk.take_profit_pct

def test_strategy_status_enum():
    """All StrategyStatus values should be parseable."""
    statuses = ["draft", "testing", "paper", "active", "archived"]
    for s in statuses:
        assert StrategyStatus(s).value == s

    assert len(StrategyStatus) == 5

    with pytest.raises(ValueError):
        StrategyStatus("invalid_status")

def test_condition_ops():
    """All ConditionOp values should exist and be usable in a Condition."""
    expected_ops = ["gt", "gte", "lt", "lte", "eq", "crosses_above", "crosses_below"]
    assert len(ConditionOp) == len(expected_ops)

    for op_str in expected_ops:
        op = ConditionOp(op_str)
        cond = Condition(left="col_a", op=op, right=50)
        assert cond.op == op

    # Column reference as right side
    cond_col = Condition(left="macd_line", op=ConditionOp.crosses_above, right="signal_line")
    assert isinstance(cond_col.right, str)

    # Numeric literal as right side
    cond_num = Condition(left="rsi_14", op=ConditionOp.gt, right=30)
    assert isinstance(cond_num.right, (int, float))

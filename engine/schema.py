"""Strategy Definition schema — the contract for the entire system."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MarketType(str, Enum):
    kr_stock = "kr_stock"
    us_stock = "us_stock"
    crypto_spot = "crypto_spot"
    crypto_futures = "crypto_futures"


class Direction(str, Enum):
    long = "long"
    short = "short"
    both = "both"


class StrategyStatus(str, Enum):
    draft = "draft"
    testing = "testing"
    active = "active"
    archived = "archived"


class ConditionOp(str, Enum):
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    eq = "eq"
    crosses_above = "crosses_above"
    crosses_below = "crosses_below"


# ---------------------------------------------------------------------------
# Indicator
# ---------------------------------------------------------------------------

class IndicatorDef(BaseModel):
    """Single technical indicator definition."""

    name: str = Field(..., description="ta-lib function name, e.g. RSI, MACD, BBANDS")
    params: dict[str, int | float] = Field(default_factory=dict)
    output: str | dict[str, str] = Field(
        ...,
        description=(
            "Single string for single-output indicators (e.g. 'rsi_14'), "
            "or dict mapping ta-lib output names to aliases for multi-output "
            "(e.g. {'macd': 'macd_line', 'macdsignal': 'signal_line'})"
        ),
    )


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

class Condition(BaseModel):
    """A single comparison condition."""

    left: str = Field(..., description="Column name or indicator alias")
    op: ConditionOp
    right: str | int | float = Field(
        ...,
        description="Column name (str) for cross-column compare, or numeric literal",
    )


class ConditionGroup(BaseModel):
    """A group of conditions combined with AND/OR logic."""

    logic: Literal["and", "or"] = "and"
    conditions: list[Condition] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

class RiskParams(BaseModel):
    stop_loss_pct: float | None = Field(None, ge=0, le=1)
    take_profit_pct: float | None = Field(None, ge=0, le=1)
    risk_per_trade_pct: float = Field(0.02, ge=0, le=1)
    trailing_stop_pct: float | None = Field(None, ge=0, le=1)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class StrategyMeta(BaseModel):
    created_at: date = Field(default_factory=date.today)
    updated_at: date | None = None
    source_references: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Regime Config (optional top-down macro overlay)
# ---------------------------------------------------------------------------

class RegimeConfig(BaseModel):
    """Configuration for the crypto macro regime overlay."""
    enabled: bool = False
    btc_ema_short: int = Field(50, ge=5, le=200)
    btc_ema_long: int = Field(200, ge=50, le=500)
    alt_basket_size: int = Field(10, ge=3, le=20)
    dominance_period: int = Field(20, ge=5, le=60)


# ---------------------------------------------------------------------------
# Top-level Strategy Definition
# ---------------------------------------------------------------------------

class StrategyDefinition(BaseModel):
    """Complete JSON strategy definition — the system-wide contract."""

    name: str
    version: str = "1.0"
    status: StrategyStatus = StrategyStatus.draft
    description: str = ""

    markets: list[MarketType] = Field(..., min_length=1)
    direction: Direction = Direction.long
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])

    indicators: list[IndicatorDef] = Field(..., min_length=1)

    entry: ConditionGroup
    exit: ConditionGroup

    risk: RiskParams = Field(default_factory=RiskParams)
    metadata: StrategyMeta = Field(default_factory=StrategyMeta)
    regime: RegimeConfig | None = None

    model_config = {"json_schema_serialization": "always"}

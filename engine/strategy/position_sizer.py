"""통합 포지션 사이징 오케스트레이터 — ATR+Kelly + position_size_factor + Risk Parity 배분.

최종 포지션 크기 = ATR+Kelly 수량 x RiskManager.position_size_factor() x allocation_weight
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from engine.strategy.scalping_risk import (
    ScalpRiskConfig,
    calculate_scalp_risk,
)

if TYPE_CHECKING:
    from engine.strategy.risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PositionSizeResult:
    """포지션 사이징 결과."""

    quantity: float
    risk_amount: float
    position_value: float
    kelly_applied: bool
    allocation_weight: float
    size_factor: float
    reason: str


class PositionSizer:
    """ATR+Kelly 기반 동적 포지션 사이징.

    - 거래 이력 충분 시 Quarter Kelly 적용, 부족 시 고정 risk_per_trade_pct
    - RiskManager.position_size_factor()로 드로다운 기반 축소
    - allocation_weight로 Risk Parity 자본 배분 반영
    """

    def __init__(
        self,
        risk_manager: RiskManager | None = None,
        default_kelly_fraction: float = 0.25,
        min_trades_for_kelly: int = 20,
    ) -> None:
        self._risk_manager = risk_manager
        self._default_kelly_fraction = default_kelly_fraction
        self._min_trades_for_kelly = min_trades_for_kelly

    def calculate(
        self,
        df: pd.DataFrame,
        entry_price: float,
        side: str,
        capital: float,
        config: ScalpRiskConfig | None = None,
        timeframe: str | None = None,
        trade_stats: dict | None = None,
        allocation_weight: float = 1.0,
    ) -> PositionSizeResult:
        """통합 포지션 사이징 계산.

        Args:
            df: OHLCV DataFrame
            entry_price: 진입 가격
            side: "long" 또는 "short"
            capital: 가용 자본 (USDT)
            config: 리스크 설정 (None이면 timeframe 기반 자동 선택)
            timeframe: 타임프레임 (config 미지정 시 프리셋 선택용)
            trade_stats: 거래 통계 (win_rate, avg_win, avg_loss, n_trades)
            allocation_weight: Risk Parity 배분 비율 (0~1, 기본 1.0)

        Returns:
            PositionSizeResult
        """
        # 1. config 결정
        if config is None and timeframe is not None:
            config = ScalpRiskConfig.for_timeframe(timeframe)

        # 2. Kelly 적용 여부 결정
        kelly_fraction: float | None = None
        kelly_applied = False
        n_trades = 0
        if trade_stats:
            n_trades = trade_stats.get("n_trades", 0)
            if n_trades >= self._min_trades_for_kelly:
                kelly_fraction = self._default_kelly_fraction
                kelly_applied = True

        # 3. effective capital = capital * allocation_weight
        effective_capital = capital * allocation_weight

        # 4. ATR+Kelly 기반 사이징
        scalp_result = calculate_scalp_risk(
            df=df,
            entry_price=entry_price,
            side=side,
            capital=effective_capital,
            config=config,
            kelly_fraction=kelly_fraction,
            trade_stats=trade_stats,
        )

        # 5. position_size_factor 곱산 (드로다운 기반 축소)
        size_factor = 1.0
        if self._risk_manager is not None:
            size_factor = self._risk_manager.position_size_factor()

        final_quantity = scalp_result.quantity * size_factor
        final_position_value = final_quantity * entry_price
        final_risk_amount = scalp_result.risk_amount * size_factor

        reason_parts = [
            scalp_result.reason,
            f"factor={size_factor:.2f}",
            f"alloc={allocation_weight:.2f}",
        ]
        if kelly_applied:
            reason_parts.append(f"kelly(n={n_trades})")
        else:
            reason_parts.append(f"fixed(n={n_trades})")

        return PositionSizeResult(
            quantity=round(final_quantity, 4),
            risk_amount=round(final_risk_amount, 4),
            position_value=round(final_position_value, 4),
            kelly_applied=kelly_applied,
            allocation_weight=allocation_weight,
            size_factor=size_factor,
            reason=" | ".join(reason_parts),
        )

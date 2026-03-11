"""PortfolioRiskManager — 다전략 상관관계 게이트 + Risk Parity 배분 연동.

신규 진입 시 기존 활성 전략과의 상관관계가 임계치를 초과하면 진입을 차단한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from engine.strategy.risk_parity import RiskParityConfig, calculate_risk_parity_weights

if TYPE_CHECKING:
    from engine.core.ports import NotificationPort

logger = logging.getLogger(__name__)

# 상관관계 계산에 필요한 최소 데이터 포인트
_MIN_DATA_POINTS = 10


@dataclass
class PortfolioRiskConfig:
    """포트폴리오 리스크 설정."""

    enabled: bool = True
    correlation_threshold: float = 0.7       # 기본 상관관계 차단 임계치
    correlation_window: int = 100            # 상관관계 계산 윈도우 (봉 수)
    strategy_overrides: dict[str, float] = field(default_factory=dict)  # {strategy_id: threshold}
    risk_parity_config: RiskParityConfig = field(default_factory=RiskParityConfig)


class PortfolioRiskManager:
    """다전략 포트폴리오 리스크 관리자.

    - 상관관계 게이트: 기존 활성 전략과 높은 상관관계를 가진 신규 진입 차단
    - Risk Parity 배분: 전략별 자본 배분 비율 관리
    """

    def __init__(
        self,
        config: PortfolioRiskConfig | None = None,
        notifier: NotificationPort | None = None,
    ) -> None:
        self._config = config or PortfolioRiskConfig()
        self._notifier = notifier
        self._active_signals: dict[str, pd.Series] = {}
        self._allocation_weights: dict[str, float] = {}

    @property
    def config(self) -> PortfolioRiskConfig:
        return self._config

    # ------------------------------------------------------------------
    # 전략 등록 / 해제
    # ------------------------------------------------------------------

    def register_strategy(self, strategy_id: str, returns: pd.Series) -> None:
        """활성 전략 등록 (수익률 시계열 저장)."""
        self._active_signals[strategy_id] = returns

    def unregister_strategy(self, strategy_id: str) -> None:
        """전략 제거 + 배분 재계산."""
        self._active_signals.pop(strategy_id, None)
        self._allocation_weights.pop(strategy_id, None)
        if self._active_signals:
            self.refresh_weights()

    # ------------------------------------------------------------------
    # 상관관계 게이트
    # ------------------------------------------------------------------

    def check_correlation_gate(
        self,
        strategy_id: str,
        signal_returns: pd.Series,
    ) -> tuple[bool, str]:
        """신규 진입 상관관계 게이트 체크.

        Returns:
            (allowed, reason) — allowed=False이면 진입 차단
        """
        if not self._config.enabled:
            return True, "gate_disabled"

        if not self._active_signals:
            return True, "no_active_strategies"

        threshold = self._config.strategy_overrides.get(
            strategy_id, self._config.correlation_threshold,
        )
        window = self._config.correlation_window

        for other_id, other_returns in self._active_signals.items():
            if other_id == strategy_id:
                continue

            corr = self._compute_correlation(signal_returns, other_returns, window)

            if corr > threshold:
                reason = (
                    f"blocked: corr={corr:.3f} with {other_id}, threshold={threshold}"
                )
                logger.info(
                    "[PortfolioRisk] %s entry blocked — %s", strategy_id, reason,
                )
                if self._notifier is not None:
                    self._notifier.send_text(
                        f"[PortfolioRisk] {strategy_id} blocked: corr={corr:.3f} with {other_id}"
                    )
                return False, reason

        return True, "passed"

    # ------------------------------------------------------------------
    # Risk Parity 배분
    # ------------------------------------------------------------------

    def get_allocation_weights(self) -> dict[str, float]:
        """캐시된 배분 비율 반환 (없으면 균등 배분)."""
        if not self._allocation_weights and self._active_signals:
            n = len(self._active_signals)
            w = 1.0 / n
            return {sid: w for sid in self._active_signals}
        return dict(self._allocation_weights)

    def refresh_weights(self) -> dict[str, float]:
        """최신 수익률로 Risk Parity 배분 재계산."""
        if not self._active_signals:
            self._allocation_weights = {}
            return {}

        self._allocation_weights = calculate_risk_parity_weights(
            self._active_signals,
            config=self._config.risk_parity_config,
        )
        return dict(self._allocation_weights)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_correlation(
        s1: pd.Series,
        s2: pd.Series,
        window: int,
    ) -> float:
        """두 수익률 시계열의 Pearson 상관계수 계산."""
        # 공통 인덱스 정렬
        combined = pd.concat([s1, s2], axis=1).dropna()

        if len(combined) < _MIN_DATA_POINTS:
            # 데이터 부족 시 상관관계 0으로 간주 (허용)
            return 0.0

        # 윈도우 적용
        if len(combined) > window:
            combined = combined.iloc[-window:]

        return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))

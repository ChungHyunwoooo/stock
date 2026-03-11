"""Risk Parity 자본 배분 — 전략별 리스크 기여 동등 배분 (numpy 직접 구현).

역분산 가중(Inverse Variance Weighting):
  - 변동성 높은 전략 -> 낮은 배분
  - 변동성 낮은 전략 -> 높은 배분
  - 합 = 1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RiskParityConfig:
    """Risk Parity 설정."""

    max_allocation_per_strategy: float = 0.4  # 전략별 최대 배분 비율
    min_allocation: float = 0.05              # 최소 배분 비율
    lookback_days: int = 60                   # 공분산 추정 윈도우


def _equal_weights(strategy_ids: list[str]) -> dict[str, float]:
    """균등 배분 fallback."""
    n = len(strategy_ids)
    if n == 0:
        return {}
    w = 1.0 / n
    return {sid: w for sid in strategy_ids}


def _apply_caps(
    weights: dict[str, float],
    config: RiskParityConfig,
) -> dict[str, float]:
    """max/min allocation cap 적용 후 재정규화.

    2-pass 잠금 방식:
      Pass 1: max cap 위반 전략 잠금 + 잔여분 재배분 (반복)
      Pass 2: min floor 위반 전략 잠금 + 잔여분 재배분 (반복)
    """
    strategy_ids = list(weights.keys())
    n = len(strategy_ids)
    if n <= 1:
        return weights

    max_cap = config.max_allocation_per_strategy
    min_floor = config.min_allocation
    apply_cap = n * max_cap >= 1.0   # cap 실현 가능할 때만
    apply_floor = n * min_floor <= 1.0

    result = dict(weights)

    # Pass 1: max cap (n * max_cap >= 1.0 일 때만 적용)
    locked: set[str] = set()
    if not apply_cap:
        return result
    for _ in range(n):
        newly_capped = [sid for sid in strategy_ids
                        if sid not in locked and result[sid] > max_cap + 1e-12]
        if not newly_capped:
            break
        for sid in newly_capped:
            result[sid] = max_cap
            locked.add(sid)
        _redistribute(result, weights, locked, strategy_ids)

    # Pass 2: min floor
    if apply_floor:
        for _ in range(n):
            newly_floored = [sid for sid in strategy_ids
                             if sid not in locked and result[sid] < min_floor - 1e-12]
            if not newly_floored:
                break
            for sid in newly_floored:
                result[sid] = min_floor
                locked.add(sid)
            _redistribute(result, weights, locked, strategy_ids)

    return result


def _redistribute(
    result: dict[str, float],
    original: dict[str, float],
    locked: set[str],
    strategy_ids: list[str],
) -> None:
    """잠긴 전략 제외, 잔여분을 원래 비율 기준으로 미잠금 전략에 재배분 (in-place)."""
    free_ids = [sid for sid in strategy_ids if sid not in locked]
    if not free_ids:
        return
    locked_sum = sum(result[sid] for sid in locked)
    remaining = 1.0 - locked_sum
    free_raw = sum(original[sid] for sid in free_ids)
    if free_raw > 0 and remaining > 0:
        for sid in free_ids:
            result[sid] = remaining * (original[sid] / free_raw)
    elif remaining > 0:
        w = remaining / len(free_ids)
        for sid in free_ids:
            result[sid] = w


def calculate_risk_parity_weights(
    returns: dict[str, pd.Series],
    config: RiskParityConfig | None = None,
) -> dict[str, float]:
    """Risk Parity 기반 전략별 자본 배분 비율 계산.

    Args:
        returns: {strategy_id: daily_returns_series}
        config: Risk Parity 설정

    Returns:
        {strategy_id: weight} (합 = 1.0)
    """
    cfg = config or RiskParityConfig()
    strategy_ids = list(returns.keys())
    n = len(strategy_ids)

    if n == 0:
        return {}
    if n == 1:
        return {strategy_ids[0]: 1.0}

    # DataFrame 변환 + lookback 윈도우
    df = pd.DataFrame(returns)
    df = df.iloc[-cfg.lookback_days:] if len(df) > cfg.lookback_days else df
    df = df.dropna()

    # 유효 행 < 5이면 균등 배분
    if len(df) < 5:
        logger.warning("Risk Parity: 유효 데이터 %d행 (< 5) — 균등 배분 fallback", len(df))
        return _equal_weights(strategy_ids)

    # 공분산 행렬
    returns_matrix = df.values  # (T, N)
    try:
        cov = np.cov(returns_matrix.T)
    except Exception:
        logger.warning("Risk Parity: 공분산 계산 실패 — 균등 배분 fallback")
        return _equal_weights(strategy_ids)

    # 단일 전략이면 cov가 스칼라
    if cov.ndim == 0:
        return _equal_weights(strategy_ids)

    # 역행렬 시도 → 역분산 가중
    try:
        inv_cov = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        # singular → pseudo-inverse
        try:
            inv_cov = np.linalg.pinv(cov)
        except Exception:
            logger.warning("Risk Parity: 역행렬 불가 — 균등 배분 fallback")
            return _equal_weights(strategy_ids)

    # Risk Parity weights: 역공분산 행 합 / 전체 합
    raw_weights = inv_cov.sum(axis=1)

    # 음수 가중치 처리 (음수면 역분산 단순 방식으로 fallback)
    if (raw_weights <= 0).any():
        # 대각 원소(분산)의 역수 사용
        variances = np.diag(cov)
        if (variances <= 0).any():
            return _equal_weights(strategy_ids)
        raw_weights = 1.0 / variances

    total = raw_weights.sum()
    if total <= 0 or not np.isfinite(total):
        return _equal_weights(strategy_ids)

    normalized = raw_weights / total
    weights = {sid: float(normalized[i]) for i, sid in enumerate(strategy_ids)}

    return _apply_caps(weights, cfg)

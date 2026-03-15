"""HMM 기반 레짐 탐지 — 은닉 마르코프 모델로 시장 상태 분류.

수익률 + 변동성 피처로 3개 은닉 상태(Hidden State) 학습:
  - State 0: 저변동 횡보 (Low Vol Ranging)
  - State 1: 고변동 추세 (Trending)
  - State 2: 극변동 위기 (Crisis/Volatile)

hmmlearn 미설치 시 ADX 기반 fallback.

사용법:
    detector = HMMRegimeDetector()
    detector.fit(df)  # 학습
    regime = detector.predict_current(df)  # 현재 레짐
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from hmmlearn.hmm import GaussianHMM
    _HMM_AVAILABLE = True
except ImportError:
    _HMM_AVAILABLE = False
    logger.info("hmmlearn 미설치 — ADX fallback 사용")


class HMMState(str, Enum):
    LOW_VOL = "LOW_VOL"       # 저변동 횡보
    TRENDING = "TRENDING"     # 추세
    CRISIS = "CRISIS"         # 극변동 위기


class AgentRegime(str, Enum):
    """에이전트 구성 기반 레짐 (L3 모드)."""
    INFO_GAME = "INFO_GAME"       # 정보 게임 (TA 유효)
    CAPITAL_GAME = "CAPITAL_GAME" # 자본 게임 (사냥 진행)
    PANIC = "PANIC"               # 패닉 (청산 폭포)


@dataclass(slots=True)
class HMMRegimeResult:
    """HMM 레짐 판단 결과."""
    state: HMMState
    state_probs: dict[str, float]  # 각 상태 확률
    volatility: float
    returns_mean: float
    confidence: float  # 가장 높은 상태 확률


class HMMRegimeDetector:
    """HMM 기반 레짐 탐지기.

    feature_mode:
      "l1": 수익률 + 변동성 (기존)
      "l3": L3 관측 벡터 (log_ret, vol, funding_z, oi_change, cvd_slope)
    """

    def __init__(
        self,
        n_states: int = 3,
        lookback: int = 252,
        vol_window: int = 20,
        feature_mode: str = "l1",
    ) -> None:
        self._n_states = n_states
        self._lookback = lookback
        self._vol_window = vol_window
        self._feature_mode = feature_mode
        self._model: GaussianHMM | None = None
        self._state_map: dict[int, HMMState] = {}
        self._agent_state_map: dict[int, AgentRegime] = {}
        self._fitted = False

    def _prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """수익률 + 변동성 피처 생성."""
        close = df["close"].values.astype(np.float64)
        returns = np.diff(np.log(close))
        vol = pd.Series(returns).rolling(self._vol_window).std().values

        # NaN 제거
        valid = ~np.isnan(vol)
        returns = returns[valid]
        vol = vol[valid]

        if len(returns) < 50:
            return np.array([])

        return np.column_stack([returns, vol])

    def _map_states(self, model: GaussianHMM) -> dict[int, HMMState]:
        """학습된 상태를 의미에 매핑 (변동성 기준 정렬)."""
        # 각 상태의 평균 변동성으로 정렬
        vol_means = model.means_[:, 1]  # 변동성 피처
        sorted_idx = np.argsort(vol_means)

        mapping = {}
        states = [HMMState.LOW_VOL, HMMState.TRENDING, HMMState.CRISIS]
        for i, idx in enumerate(sorted_idx):
            if i < len(states):
                mapping[int(idx)] = states[i]
        return mapping

    def fit_l3(self, observations: np.ndarray) -> bool:
        """L3 관측 벡터로 HMM 학습.

        Args:
            observations: shape=(n, 5) from observation.build_from_sim/real
                          NaN 행은 사전 제거 필요
        """
        if not _HMM_AVAILABLE:
            logger.warning("hmmlearn 미설치 — fit_l3 스킵")
            return False

        if len(observations) < 50:
            return False

        try:
            model = GaussianHMM(
                n_components=self._n_states,
                covariance_type="full",
                n_iter=100,
                random_state=42,
            )
            model.fit(observations)
            self._model = model
            self._agent_state_map = self._map_agent_states(model)
            self._fitted = True
            logger.info("HMM L3 학습 완료: %d 상태, %d 샘플", self._n_states, len(observations))
            return True
        except Exception as e:
            logger.error("HMM L3 학습 실패: %s", e)
            return False

    def predict_l3(self, observations: np.ndarray) -> list[dict]:
        """L3 관측 벡터로 레짐 시퀀스 예측.

        Returns:
            [{state: AgentRegime, probs: {state: float}, step: int}, ...]
        """
        if not self._fitted or self._model is None:
            return []

        try:
            probs = self._model.predict_proba(observations)
            results = []
            for i, prob in enumerate(probs):
                state_idx = int(np.argmax(prob))
                state = self._agent_state_map.get(state_idx, AgentRegime.INFO_GAME)
                state_probs = {
                    self._agent_state_map.get(j, AgentRegime.INFO_GAME).value: float(prob[j])
                    for j in range(len(prob))
                }
                results.append({"state": state, "probs": state_probs, "step": i})
            return results
        except Exception as e:
            logger.warning("HMM L3 예측 실패: %s", e)
            return []

    def _map_agent_states(self, model: GaussianHMM) -> dict[int, AgentRegime]:
        """L3 학습 상태를 에이전트 레짐에 매핑.

        변동성(col 1) 기준 정렬:
          최저 변동성 → INFO_GAME (안정, TA 유효)
          중간 변동성 → CAPITAL_GAME (사냥, 쏠림)
          최고 변동성 → PANIC (청산 폭포)
        """
        vol_means = model.means_[:, 1]  # col 1 = volatility
        sorted_idx = np.argsort(vol_means)
        regimes = [AgentRegime.INFO_GAME, AgentRegime.CAPITAL_GAME, AgentRegime.PANIC]
        mapping = {}
        for i, idx in enumerate(sorted_idx):
            if i < len(regimes):
                mapping[int(idx)] = regimes[i]
        return mapping

    def fit(self, df: pd.DataFrame) -> bool:
        """HMM 학습 (L1 모드)."""
        if not _HMM_AVAILABLE:
            logger.warning("hmmlearn 미설치 — fit 스킵")
            return False

        features = self._prepare_features(df)
        if len(features) == 0:
            return False

        try:
            model = GaussianHMM(
                n_components=self._n_states,
                covariance_type="full",
                n_iter=100,
                random_state=42,
            )
            model.fit(features)
            self._model = model
            self._state_map = self._map_states(model)
            self._fitted = True
            logger.info("HMM 학습 완료: %d 상태, %d 샘플", self._n_states, len(features))
            return True
        except Exception as e:
            logger.error("HMM 학습 실패: %s", e)
            return False

    def predict_current(self, df: pd.DataFrame) -> HMMRegimeResult:
        """현재 레짐 예측."""
        close = df["close"].values.astype(np.float64)
        returns = np.diff(np.log(close))
        vol = float(pd.Series(returns).rolling(self._vol_window).std().iloc[-1])
        ret_mean = float(np.mean(returns[-self._vol_window:]))

        if not self._fitted or self._model is None or not _HMM_AVAILABLE:
            return self._fallback(vol, ret_mean)

        features = self._prepare_features(df)
        if len(features) == 0:
            return self._fallback(vol, ret_mean)

        try:
            probs = self._model.predict_proba(features)
            current_probs = probs[-1]
            state_idx = int(np.argmax(current_probs))
            state = self._state_map.get(state_idx, HMMState.LOW_VOL)

            state_probs = {
                self._state_map.get(i, HMMState.LOW_VOL).value: float(current_probs[i])
                for i in range(len(current_probs))
            }

            return HMMRegimeResult(
                state=state,
                state_probs=state_probs,
                volatility=round(vol, 6),
                returns_mean=round(ret_mean, 6),
                confidence=round(float(np.max(current_probs)), 4),
            )
        except Exception as e:
            logger.warning("HMM 예측 실패: %s", e)
            return self._fallback(vol, ret_mean)

    def _fallback(self, vol: float, ret_mean: float) -> HMMRegimeResult:
        """hmmlearn 미설치 시 간단한 규칙 기반 fallback."""
        if np.isnan(vol):
            vol = 0.01

        if vol > 0.03:
            state = HMMState.CRISIS
        elif vol > 0.015:
            state = HMMState.TRENDING
        else:
            state = HMMState.LOW_VOL

        return HMMRegimeResult(
            state=state,
            state_probs={s.value: 0.33 for s in HMMState},
            volatility=round(vol, 6),
            returns_mean=round(ret_mean, 6),
            confidence=0.5,
        )

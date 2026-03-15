"""ABM 시뮬레이터 설정 — 에이전트 파라미터 분포 + DSE sweep.

에이전트는 유형이 아닌 연속 파라미터 공간의 점.
행동은 파라미터 조합에서 자연 발생.

파라미터 근거:
  capital:              BTC 지갑 분포 (로그정규, 상위 2.3%가 95% 보유)
  max_leverage:         CoinGlass 평균 레버리지 통계 (5~8x, 꼬리 20x)
  info_level:           Kyle(1985) 정보 비대칭 — 자본과 양의 상관
  risk_tolerance:       Kahneman(1979) 전망이론 실험 — 중앙값 0.5
  herd_sensitivity:     Lux(1995) 군집행동 모델 α₁ 파라미터
  momentum_weight:      Brock-Hommes(1998) 적응적 선택 — 60% 추세추종자
  mean_reversion_weight: Brock-Hommes(1998) — momentum과 독립
  loss_aversion:        Kahneman-Tversky(1979) λ=2.25 메타분석
  reaction_speed:       Lo-Repin(2007) 트레이더 반응 실험
  position_patience:    Frydman(2012) 처분효과 fMRI 연구
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 파라미터 분포 정의
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ParamDist:
    """단일 파라미터의 샘플링 분포."""
    dist: str                    # "normal", "lognormal", "beta", "uniform", "constant"
    params: dict[str, float]     # 분포별 모수
    clip: tuple[float, float] | None = None  # 값 범위 제한

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"dist": self.dist, "params": self.params}
        if self.clip is not None:
            d["clip"] = list(self.clip)
        return d


# ---------------------------------------------------------------------------
# 시뮬레이션 설정
# ---------------------------------------------------------------------------

@dataclass
class AgentPool:
    """에이전트 모집단. 복수 모집단으로 시장 구성 가능."""
    weight: float                          # 비율 (0~1, pools 내 합=1)
    params: dict[str, ParamDist]           # 해당 모집단의 파라미터 분포

    def to_dict(self) -> dict:
        return {
            "weight": self.weight,
            "params": {k: v.to_dict() for k, v in self.params.items()},
        }


@dataclass
class SimConfig:
    """시뮬레이션 전체 설정."""
    n_agents: int                          # 에이전트 수
    agent_params: dict[str, ParamDist]     # 파라미터명 → 분포 (단일 풀 하위호환)
    pools: list[AgentPool] | None = None   # 복수 모집단 (있으면 agent_params 무시)
    n_steps: int = 2000                    # 시뮬레이션 봉 수
    initial_price: float = 100.0           # 초기 가격
    fundamental_vol: float = 0.001         # 기준가 랜덤워크 변동성 (봉당)
    tick_size: float = 0.01                # 최소 가격 단위
    liquidity: float = 100_000.0           # 기본 유동성 (Kyle lambda 역수)
    funding_interval: int = 480            # 펀딩비 정산 간격 (봉 수, 8h=480×1m)
    liquidation_threshold: float = 0.05    # 청산 기준 (마진 비율)
    warmup_steps: int = 50                 # 지표 부트스트랩용 사전 봉 수
    random_seed: int = 42                  # 재현성

    # --- 시뮬레이터 하이퍼파라미터 (DSE 캘리브레이션 대상) ---
    # 가격 영향
    target_impact_pct: float = 0.003       # 평균 주문의 목표 가격 영향 (%)
    conviction_base: float = 0.1           # 주문 크기 = capital * leverage * conviction_base
    dp_clip: float = 0.05                  # 단일 봉 최대 가격 변동 (±%)
    liq_dp_clip: float = 0.03             # 단일 청산 최대 가격 영향 (±%)

    # 복원력
    reversion_strength: float = 0.5        # Brock-Hommes 비선형 복원 계수
    reversion_sigmoid_k: float = 20.0      # 노이즈 복원 sigmoid 민감도

    # 노이즈
    noise_floor_ratio: float = 0.5         # 노이즈 최소 크기 (avg_order 대비)
    noise_agent_ratio: float = 0.3         # 노이즈 크기 (에이전트 주문 대비)
    noise_dp_ratio: float = 0.3            # 노이즈 변동 (dp 대비 비율)
    noise_dp_floor: float = 0.0003         # 노이즈 최소 변동 (%)
    warmup_noise: float = 0.001            # warmup 가격 노이즈

    # 펀딩비
    funding_scale: float = 0.002           # 펀딩비 = (long_ratio - 0.5) * scale

    # 에이전트 의사결정 계수
    funding_norm: float = 0.0001           # 펀딩비 z-score 정규화 기준
    funding_signal_weight: float = 0.3     # 펀딩비 신호 강도
    loss_exit_pressure: float = 0.5        # 손실 구간 exit 압력
    profit_exit_pressure: float = 0.3      # 수익 구간 exit 압력
    adaptation_decay: float = 0.5          # 적응적 전략 전환 감쇠
    threshold_scale: float = 0.3           # 실행 임계값 스케일
    cooldown_scale: float = 10.0           # 반응 지연 스케일
    position_size_ratio: float = 0.1       # 포지션 사이징 비율
    info_thresholds: tuple[float, float, float] = (0.2, 0.4, 0.6)  # 정보 필터 임계값
    initial_volatility: float = 0.01       # 초기 변동성 fallback

    # Stochastic volatility (변동성 클러스터링)
    sv_persistence: float = 0.85           # 변동성 자기상관 (GARCH α+β에 대응, 0~1)
    sv_reaction: float = 0.10              # 수익률 충격 → 변동성 반응 강도
    sv_mean: float = 0.01                  # 장기 평균 변동성

    def to_dict(self) -> dict:
        return {
            "n_agents": self.n_agents,
            "agent_params": {k: v.to_dict() for k, v in self.agent_params.items()},
            "n_steps": self.n_steps,
            "initial_price": self.initial_price,
            "tick_size": self.tick_size,
            "liquidity": self.liquidity,
            "funding_interval": self.funding_interval,
            "liquidation_threshold": self.liquidation_threshold,
            "random_seed": self.random_seed,
        }


# ---------------------------------------------------------------------------
# 프리셋 — 학술 근거 기반 분포 모수
# ---------------------------------------------------------------------------

_BASE_PARAMS: dict[str, ParamDist] = {
    # 자본금: 로그정규 (e^7≈1100 중심, 넓은 분산 → 소수 고래)
    "capital": ParamDist("lognormal", {"mean": 7.0, "sigma": 2.0}, clip=(100, 10_000_000)),
    # 최대 레버리지: 로그정규 (중앙 ~4.5x, 꼬리 20x)
    "max_leverage": ParamDist("lognormal", {"mean": 1.5, "sigma": 0.8}, clip=(1, 20)),
    # 정보 수준: 베타 (대부분 낮음, 소수 높음)
    "info_level": ParamDist("beta", {"a": 2.0, "b": 5.0}),
    # 리스크 허용도: 정규 (중앙 0.5)
    "risk_tolerance": ParamDist("normal", {"mean": 0.5, "std": 0.15}, clip=(0.05, 0.95)),
    # 군집 민감도: 베타 (약간 높은 쪽 치우침)
    "herd_sensitivity": ParamDist("beta", {"a": 3.0, "b": 2.0}),
    # 모멘텀 추종: 정규 (양수 치우침 — 60% 추세추종자)
    "momentum_weight": ParamDist("normal", {"mean": 0.3, "std": 0.4}, clip=(-1, 1)),
    # 평균회귀: 정규 (약한 양수)
    "mean_reversion_weight": ParamDist("normal", {"mean": 0.1, "std": 0.3}, clip=(-1, 1)),
    # 손실회피: 정규 (Kahneman λ=2.25)
    "loss_aversion": ParamDist("normal", {"mean": 2.25, "std": 0.5}, clip=(1.0, 4.0)),
    # 반응 속도: 베타 (대부분 중간~느림)
    "reaction_speed": ParamDist("beta", {"a": 2.0, "b": 3.0}),
    # 포지션 인내도: 베타 (균등 분포에 가까움)
    "position_patience": ParamDist("beta", {"a": 2.0, "b": 2.0}),
}


def _make_preset(overrides: dict[str, dict[str, Any]] | None = None, **kwargs: Any) -> SimConfig:
    """기본 파라미터에 오버라이드 적용하여 SimConfig 생성."""
    params = {k: copy.deepcopy(v) for k, v in _BASE_PARAMS.items()}
    if overrides:
        for param_name, changes in overrides.items():
            if param_name in params:
                for field_name, value in changes.items():
                    if field_name == "dist":
                        params[param_name].dist = value
                    elif field_name == "clip":
                        params[param_name].clip = tuple(value)
                    else:
                        params[param_name].params[field_name] = value
    return SimConfig(agent_params=params, **kwargs)


PRESETS: dict[str, SimConfig] = {
    # 정보 게임: 정보 대칭, 자본 분산, 낮은 레버리지
    "information_game": _make_preset(
        n_agents=200,
        n_steps=2000,
        liquidity=150_000,
        overrides={
            "capital": {"sigma": 1.5},         # 자본 격차 작음
            "max_leverage": {"mean": 1.0},     # 낮은 레버리지
            "info_level": {"a": 3.0, "b": 3.0},  # 정보 균등 분포
            "herd_sensitivity": {"a": 2.0, "b": 3.0},  # 군집 약함
        },
    ),

    # 자본 게임: 자본 집중, 높은 레버리지, 정보 비대칭
    "capital_game": _make_preset(
        n_agents=200,
        n_steps=2000,
        liquidity=80_000,
        overrides={
            "capital": {"sigma": 2.5},         # 자본 격차 극심
            "max_leverage": {"mean": 2.0},     # 높은 레버리지
            "info_level": {"a": 1.5, "b": 6.0},  # 대부분 정보 부족
            "herd_sensitivity": {"a": 4.0, "b": 1.5},  # 군집 강함
            "momentum_weight": {"mean": 0.5},  # 추세추종 강함
        },
    ),

    # 패닉: 극단 레버리지, 강한 군집, 빠른 반응
    "panic": _make_preset(
        n_agents=200,
        n_steps=2000,
        liquidity=50_000,
        overrides={
            "capital": {"sigma": 2.0},
            "max_leverage": {"mean": 2.5, "sigma": 1.0},
            "herd_sensitivity": {"a": 5.0, "b": 1.0},  # 극단적 군집
            "risk_tolerance": {"mean": 0.6},    # 리스크 추구
            "loss_aversion": {"mean": 2.8},     # 강한 손실회피
            "reaction_speed": {"a": 4.0, "b": 2.0},  # 빠른 반응
        },
    ),
}


# ---------------------------------------------------------------------------
# DSE Sweep
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SweepAxis:
    """탐색 축. target은 'param_name.dist_param' 형식."""
    target: str          # 예: "capital.sigma", "herd_sensitivity.a"
    values: list[float]  # 탐색할 값 목록


@dataclass
class SweepConfig:
    """DSE 탐색 설정."""
    base: SimConfig
    axes: list[SweepAxis] = field(default_factory=list)


def generate_sweep_configs(sweep: SweepConfig) -> list[tuple[dict[str, float], SimConfig]]:
    """SweepConfig → (label_dict, SimConfig) 리스트 (직곱).

    Returns:
        [({"capital.sigma": 1.0, "herd.a": 3.0}, SimConfig), ...]
    """
    if not sweep.axes:
        return [({}, copy.deepcopy(sweep.base))]

    axis_names = [a.target for a in sweep.axes]
    axis_values = [a.values for a in sweep.axes]

    results: list[tuple[dict[str, float], SimConfig]] = []
    for combo in itertools.product(*axis_values):
        labels = dict(zip(axis_names, combo))
        config = copy.deepcopy(sweep.base)

        for target, value in labels.items():
            parts = target.split(".")
            if len(parts) == 1:
                # SimConfig 직접 필드 (adaptation_decay, reversion_strength 등)
                if hasattr(config, target):
                    setattr(config, target, type(getattr(config, target))(value))
            elif parts[0].startswith("pools["):
                # pools[idx].weight or pools[idx].param_name.dist_field
                idx_str = parts[0].split("[")[1].rstrip("]")
                pool_idx = int(idx_str)
                if config.pools and pool_idx < len(config.pools):
                    pool = config.pools[pool_idx]
                    if len(parts) == 2 and parts[1] == "weight":
                        pool.weight = float(value)
                    elif len(parts) == 3 and parts[1] in pool.params:
                        pool.params[parts[1]].params[parts[2]] = value
            elif len(parts) == 2:
                param_name, dist_param = parts
                if param_name in config.agent_params:
                    if dist_param == "dist":
                        config.agent_params[param_name].dist = str(value)
                    elif dist_param in ("clip_min", "clip_max"):
                        clip = config.agent_params[param_name].clip or (0, float("inf"))
                        if dist_param == "clip_min":
                            config.agent_params[param_name].clip = (value, clip[1])
                        else:
                            config.agent_params[param_name].clip = (clip[0], value)
                    else:
                        config.agent_params[param_name].params[dist_param] = value

        results.append((labels, config))

    return results

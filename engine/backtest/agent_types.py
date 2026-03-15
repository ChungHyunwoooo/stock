"""ABM 에이전트 — 파라미터 기반 의사결정.

단일 decide() 함수에서 파라미터 값에 따라 모든 행동이 결정.
유형 분기 없음. 행동은 파라미터 공간에서 자연 발생.

의사결정 흐름:
  정보 필터(info_level) → 방향 판단(momentum/mean_reversion)
  → 군집 효과(herd) → 손실회피 왜곡(loss_aversion)
  → 실행 임계값(risk_tolerance) → 반응 속도 필터(reaction_speed)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine.backtest.agent_config import AgentPool, ParamDist, SimConfig


# ---------------------------------------------------------------------------
# 시장 상태 — 에이전트가 보는 세계
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MarketState:
    """매 스텝 에이전트에게 전달되는 시장 정보."""
    price: float
    returns_ma_short: float    # 단기 수익률 이동평균 (5봉)
    returns_ma_long: float     # 장기 수익률 이동평균 (50봉)
    price_deviation: float     # 가격의 기준가 대비 편차 (%)
    volatility_short: float    # 단기 변동성 (10봉)
    volatility_long: float     # 장기 변동성 (50봉)
    market_sentiment: float    # 전체 에이전트 순포지션 방향 (-1~1)
    oi_total: float            # 전체 OI (포지션 절대합)
    oi_long_ratio: float       # 롱 비율 (0~1)
    funding_rate: float        # 시뮬 펀딩비
    volume_ma: float           # 최근 거래량 이동평균


def filter_by_info(
    state: MarketState,
    info_level: float,
    thresholds: tuple[float, float, float],
) -> MarketState:
    """info_level에 따라 관측 가능한 정보를 제한.

    thresholds = (t1, t2, t3):
      < t1: 가격만
      t1~t2: + 수익률/변동성
      t2~t3: + 거래량/sentiment
      >= t3: + 펀딩비/OI
    """
    t1, t2, t3 = thresholds
    nan = float("nan")
    return MarketState(
        price=state.price,
        returns_ma_short=state.returns_ma_short if info_level >= t1 else nan,
        returns_ma_long=state.returns_ma_long if info_level >= t1 else nan,
        price_deviation=state.price_deviation if info_level >= t1 else nan,
        volatility_short=state.volatility_short if info_level >= t1 else nan,
        volatility_long=state.volatility_long if info_level >= t1 else nan,
        market_sentiment=state.market_sentiment if info_level >= t2 else nan,
        oi_total=state.oi_total if info_level >= t3 else nan,
        oi_long_ratio=state.oi_long_ratio if info_level >= t3 else nan,
        funding_rate=state.funding_rate if info_level >= t3 else nan,
        volume_ma=state.volume_ma if info_level >= t2 else nan,
    )


# ---------------------------------------------------------------------------
# 주문
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Order:
    """에이전트 주문."""
    agent_id: int
    side: str       # "buy" | "sell"
    size: float     # 수량 (양수)


# ---------------------------------------------------------------------------
# 에이전트
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    """파라미터 기반 에이전트.

    모든 행동은 10개 연속 파라미터의 조합에서 결정.
    """
    agent_id: int
    capital: float
    max_leverage: float
    info_level: float
    risk_tolerance: float
    herd_sensitivity: float
    momentum_weight: float
    mean_reversion_weight: float
    loss_aversion: float
    reaction_speed: float
    position_patience: float

    # 상태 (시뮬 중 업데이트)
    position: float = 0.0          # 양수=롱, 음수=숏
    entry_price: float = 0.0       # 평균 진입가
    realized_pnl: float = 0.0      # 누적 실현 손익
    is_liquidated: bool = False    # 청산 여부
    _cooldown: int = 0             # 반응 지연 잔여 봉 수
    _last_signal: float = 0.0      # 적응적 전략 전환용: 직전 신호

    # 내부 RNG
    _rng: np.random.Generator = field(
        default_factory=lambda: np.random.default_rng(), repr=False,
    )

    @property
    def unrealized_pnl(self) -> float:
        """미실현 손익 (마지막으로 본 가격 기준)."""
        return self.position * (self._last_price - self.entry_price) if self.position != 0 else 0.0

    @property
    def margin_used(self) -> float:
        """사용 중인 마진."""
        return abs(self.position) * self.entry_price / self.max_leverage if self.entry_price > 0 else 0.0

    def _init_last_price(self, price: float) -> None:
        self._last_price = price

    def decide(self, state: MarketState, config: SimConfig) -> Order | None:
        """시장 상태를 보고 주문 결정.

        단일 함수에서 파라미터가 행동을 결정. 매직넘버 없음 — 전부 config.
        """
        if self.is_liquidated:
            return None

        self._last_price = state.price

        # 0. 반응 지연
        if self._cooldown > 0:
            self._cooldown -= 1
            return None

        # 1. 정보 필터
        visible = filter_by_info(state, self.info_level, config.info_thresholds)

        # 2. 방향 판단 — 시간 스케일 분리
        #    빠른 에이전트(speed↑): 단기 수익률 중심 → 단기 평균회귀
        #    느린 에이전트(speed↓): 장기 수익률 중심 → 장기 모멘텀 유지
        signal = 0.0
        speed = self.reaction_speed

        # 단기/장기 혼합: speed가 높을수록 단기 비중↑
        ret_short = visible.returns_ma_short if not np.isnan(visible.returns_ma_short) else 0.0
        ret_long = visible.returns_ma_long if not np.isnan(visible.returns_ma_long) else 0.0
        returns_ma = speed * ret_short + (1 - speed) * ret_long

        vol_short = visible.volatility_short if not np.isnan(visible.volatility_short) else 1e-4
        vol_long = visible.volatility_long if not np.isnan(visible.volatility_long) else 1e-4
        vol_scale = max(speed * vol_short + (1 - speed) * vol_long, 1e-6)

        if abs(returns_ma) > 1e-10:
            signal += self.momentum_weight * (returns_ma / vol_scale)

        if not np.isnan(visible.price_deviation):
            signal += self.mean_reversion_weight * (-visible.price_deviation / vol_scale)

        # 3. 군집 효과
        if not np.isnan(visible.market_sentiment):
            signal += self.herd_sensitivity * visible.market_sentiment

        # 4. 펀딩비 역발상
        if not np.isnan(visible.funding_rate):
            funding_z = visible.funding_rate / config.funding_norm
            signal -= funding_z * config.funding_signal_weight * (1 - self.herd_sensitivity)

        # 5. 손실회피 왜곡 (Kahneman)
        if self.position != 0:
            pnl = self.unrealized_pnl
            if pnl < 0:
                exit_pressure = -config.loss_exit_pressure / self.loss_aversion
                signal += exit_pressure if self.position > 0 else -exit_pressure
            else:
                exit_pressure = config.profit_exit_pressure * (1 - self.position_patience)
                signal -= exit_pressure if self.position > 0 else -exit_pressure

        # 6. 적응적 전략 전환 (Brock-Hommes)
        if self.position != 0 and self._last_signal != 0:
            pnl = self.unrealized_pnl
            signal_was_right = (self._last_signal > 0 and pnl > 0) or (self._last_signal < 0 and pnl < 0)
            if not signal_was_right:
                signal *= config.adaptation_decay

        self._last_signal = signal

        # 7. 실행 임계값
        threshold = config.threshold_scale * (1 - self.risk_tolerance)
        if abs(signal) < threshold:
            return None

        # 8. 반응 지연 쿨다운
        self._cooldown = int((1 - self.reaction_speed) * config.cooldown_scale * self._rng.exponential(1.0))

        # 9. 포지션 크기 계산
        conviction = min(abs(signal), 1.0)
        max_position_value = self.capital * self.max_leverage
        target_size = max_position_value * conviction * config.position_size_ratio / state.price

        side = "buy" if signal > 0 else "sell"

        # 기존 포지션과 같은 방향이면 추가, 반대면 청산/반전
        if side == "buy" and self.position >= 0:
            # 롱 추가 — 최대 포지션 제한
            current_value = abs(self.position) * state.price
            remaining = max(0, max_position_value - current_value)
            size = min(target_size, remaining / state.price) if state.price > 0 else 0
        elif side == "sell" and self.position <= 0:
            # 숏 추가
            current_value = abs(self.position) * state.price
            remaining = max(0, max_position_value - current_value)
            size = min(target_size, remaining / state.price) if state.price > 0 else 0
        else:
            # 반대 방향 — 기존 포지션 청산 (일부 또는 전체)
            size = min(target_size, abs(self.position))

        if size < 1e-10:
            return None

        return Order(agent_id=self.agent_id, side=side, size=size)

    def apply_fill(self, side: str, size: float, price: float) -> None:
        """체결 반영."""
        if side == "buy":
            if self.position >= 0:
                # 롱 추가
                total_cost = self.position * self.entry_price + size * price
                self.position += size
                self.entry_price = total_cost / self.position if self.position > 0 else price
            else:
                # 숏 청산
                closed = min(size, abs(self.position))
                self.realized_pnl += closed * (self.entry_price - price)
                self.position += closed
                if size > closed:
                    # 반전 → 롱
                    remaining = size - closed
                    self.position = remaining
                    self.entry_price = price
                elif self.position == 0:
                    self.entry_price = 0.0
        else:  # sell
            if self.position <= 0:
                # 숏 추가
                total_cost = abs(self.position) * self.entry_price + size * price
                self.position -= size
                self.entry_price = total_cost / abs(self.position) if self.position != 0 else price
            else:
                # 롱 청산
                closed = min(size, self.position)
                self.realized_pnl += closed * (price - self.entry_price)
                self.position -= closed
                if size > closed:
                    # 반전 → 숏
                    remaining = size - closed
                    self.position = -remaining
                    self.entry_price = price
                elif self.position == 0:
                    self.entry_price = 0.0

    def check_liquidation(self, price: float, threshold: float) -> bool:
        """강제 청산 여부 확인."""
        if self.position == 0 or self.is_liquidated:
            return False

        unrealized = self.position * (price - self.entry_price)
        margin = abs(self.position) * self.entry_price / self.max_leverage

        if margin <= 0:
            return False

        # 마진 대비 손실이 임계값 초과 → 청산
        if -unrealized >= margin * (1 - threshold):
            self.is_liquidated = True
            return True
        return False

    def liquidation_order(self) -> Order:
        """강제 청산 주문 생성."""
        side = "sell" if self.position > 0 else "buy"
        return Order(agent_id=self.agent_id, side=side, size=abs(self.position))


# ---------------------------------------------------------------------------
# 에이전트 샘플링
# ---------------------------------------------------------------------------

def _sample_param(dist: ParamDist, rng: np.random.Generator) -> float:
    """분포 정의에서 단일 값 샘플링."""
    p = dist.params
    if dist.dist == "normal":
        val = rng.normal(p["mean"], p.get("std", 1.0))
    elif dist.dist == "lognormal":
        val = rng.lognormal(p["mean"], p.get("sigma", 1.0))
    elif dist.dist == "beta":
        val = rng.beta(p["a"], p["b"])
    elif dist.dist == "uniform":
        val = rng.uniform(p.get("low", 0), p.get("high", 1))
    elif dist.dist == "constant":
        val = p["value"]
    else:
        raise ValueError(f"Unknown distribution: {dist.dist}")

    if dist.clip is not None:
        val = max(dist.clip[0], min(dist.clip[1], val))

    return float(val)


def _make_agent(agent_id: int, param_dists: dict[str, ParamDist], rng: np.random.Generator, seed_base: int) -> Agent:
    """파라미터 분포에서 단일 에이전트 생성."""
    params = {name: _sample_param(dist, rng) for name, dist in param_dists.items()}
    return Agent(
        agent_id=agent_id,
        capital=params["capital"],
        max_leverage=params["max_leverage"],
        info_level=params["info_level"],
        risk_tolerance=params["risk_tolerance"],
        herd_sensitivity=params["herd_sensitivity"],
        momentum_weight=params["momentum_weight"],
        mean_reversion_weight=params["mean_reversion_weight"],
        loss_aversion=params["loss_aversion"],
        reaction_speed=params["reaction_speed"],
        position_patience=params["position_patience"],
        _rng=np.random.default_rng(seed_base + agent_id + 1),
    )


def sample_agents(config: SimConfig) -> list[Agent]:
    """SimConfig에서 에이전트 n명 샘플링.

    pools가 있으면 각 풀의 weight 비율로 배분.
    없으면 agent_params 단일 분포 사용 (하위호환).
    """
    rng = np.random.default_rng(config.random_seed)
    agents: list[Agent] = []

    if config.pools:
        # 풀별 에이전트 수 배분
        weights = [p.weight for p in config.pools]
        total_w = sum(weights)
        counts = [int(config.n_agents * w / total_w) for w in weights]
        # 반올림 오차 보정: 남은 수를 첫 풀에 추가
        remainder = config.n_agents - sum(counts)
        counts[0] += remainder

        agent_id = 0
        for pool, count in zip(config.pools, counts):
            for _ in range(count):
                agents.append(_make_agent(agent_id, pool.params, rng, config.random_seed))
                agent_id += 1
    else:
        # 단일 분포 (하위호환)
        for i in range(config.n_agents):
            agents.append(_make_agent(i, config.agent_params, rng, config.random_seed))

    return agents

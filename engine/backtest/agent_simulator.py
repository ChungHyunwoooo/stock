"""ABM 시뮬레이션 엔진 — 에이전트 상호작용 → 가격 형성 → OHLCV + L3 생성.

가격 영향 모델: Kyle(1985) Δp = λ · net_order_size
청산 모델: Brunnermeier-Pedersen(2009) 유동성 나선
봉 생성: 스텝 내 주문 흐름에서 OHLCV 구성
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine.backtest.agent_config import SimConfig
from engine.backtest.agent_types import Agent, MarketState, Order, sample_agents

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 시뮬레이션 결과
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    """시뮬레이션 출력."""
    config: SimConfig
    ohlcv: pd.DataFrame              # 생성된 차트 (open, high, low, close, volume)
    l3_data: pd.DataFrame            # 시뮬 L3 (funding, oi, cvd, ls_ratio)
    agent_summary: pd.DataFrame      # 에이전트별 최종 상태
    liquidations: list[dict]         # 청산 이벤트 로그
    stats: dict                      # 기본 통계


# ---------------------------------------------------------------------------
# 시뮬 엔진
# ---------------------------------------------------------------------------

def simulate(config: SimConfig) -> SimResult:
    """에이전트 시뮬레이션 실행.

    Args:
        config: 시뮬레이션 설정 (에이전트 분포, 봉 수, 유동성 등)

    Returns:
        SimResult with OHLCV, L3, agent summary, liquidations
    """
    rng = np.random.default_rng(config.random_seed)
    agents = sample_agents(config)
    for a in agents:
        a._init_last_price(config.initial_price)

    price = config.initial_price
    fundamental = config.initial_price  # 기준가 (Brock-Hommes p*)

    # Kyle's lambda 자동 캘리브레이션
    avg_max_position_value = float(np.mean([
        a.capital * a.max_leverage for a in agents
    ]))
    avg_order_value = avg_max_position_value * config.conviction_base
    avg_order_size = avg_order_value / price
    lambda_ = (config.target_impact_pct * price) / max(avg_order_size, 1e-10)

    # Warmup: 기준가 랜덤워크로 초기 가격 히스토리 생성 (지표 부트스트랩)
    price_history: list[float] = [price]
    return_history: list[float] = [0.0]
    volume_history: list[float] = [0.0]

    for _ in range(config.warmup_steps):
        fundamental *= np.exp(rng.normal(0, config.fundamental_vol))
        warmup_price = fundamental * (1 + rng.normal(0, config.warmup_noise))
        warmup_price = max(config.tick_size, warmup_price)
        log_ret = np.log(warmup_price / price_history[-1]) if price_history[-1] > 0 else 0.0
        price_history.append(warmup_price)
        return_history.append(log_ret)
        volume_history.append(avg_order_size * rng.exponential(1.0))

    price = price_history[-1]
    fundamental = price  # warmup 이후 기준가 동기화

    # Stochastic volatility 상태 (GARCH(1,1) 간소화)
    # σ²_t = sv_mean*(1-α-β) + α*r²_{t-1} + β*σ²_{t-1}
    sv_var = config.sv_mean ** 2  # 초기 분산

    # 결과 저장
    ohlcv_rows: list[dict] = []
    l3_rows: list[dict] = []
    liquidation_log: list[dict] = []
    cvd_cumulative = 0.0
    pending_liquidations: list[int] = []  # 다음 봉에서 처리할 청산 에이전트 ID

    for step in range(config.n_steps):
        # 기준가 랜덤워크 (Brock-Hommes p*)
        fundamental *= np.exp(rng.normal(0, config.fundamental_vol))

        # --- 시장 상태 구성 (단기/장기 분리) ---
        short_w = min(5, len(return_history))
        long_w = min(50, len(return_history))
        returns_ma_short = float(np.mean(return_history[-short_w:])) if short_w > 0 else 0.0
        returns_ma_long = float(np.mean(return_history[-long_w:])) if long_w > 0 else 0.0
        price_deviation = (price - fundamental) / fundamental if fundamental > 0 else 0.0
        volatility_short = float(np.std(return_history[-min(10, len(return_history)):])) if len(return_history) > 2 else config.initial_volatility
        volatility_long = float(np.std(return_history[-long_w:])) if long_w > 2 else config.initial_volatility
        vol_ma = float(np.mean(volume_history[-min(20, len(volume_history)):])) if len(volume_history) > 0 else 0.0

        # 에이전트 포지션 집계
        total_long = sum(a.position for a in agents if a.position > 0 and not a.is_liquidated)
        total_short = sum(abs(a.position) for a in agents if a.position < 0 and not a.is_liquidated)
        oi_total = total_long + total_short
        oi_long_ratio = total_long / oi_total if oi_total > 0 else 0.5
        net_position = total_long - total_short
        max_pos = max(total_long + total_short, 1.0)
        market_sentiment = net_position / max_pos

        # 펀딩비: 롱/숏 불균형 기반
        funding_rate = (oi_long_ratio - 0.5) * config.funding_scale

        state = MarketState(
            price=price,
            returns_ma_short=returns_ma_short,
            returns_ma_long=returns_ma_long,
            price_deviation=price_deviation,
            volatility_short=volatility_short,
            volatility_long=volatility_long,
            market_sentiment=market_sentiment,
            oi_total=oi_total,
            oi_long_ratio=oi_long_ratio,
            funding_rate=funding_rate,
            volume_ma=vol_ma,
        )

        # --- 주문 수집 ---
        orders: list[Order] = []
        for agent in agents:
            if agent.is_liquidated:
                continue
            order = agent.decide(state, config)
            if order is not None:
                orders.append(order)

        # 시장 노이즈 주문 (미모델링 참여자 + fundamental 복원력)
        # Lux-Marchesi: 펀더멘털리스트는 항상 p* 방향으로 거래
        agent_volume = sum(o.size for o in orders)
        noise_floor = avg_order_size * config.noise_floor_ratio
        noise_size = max(noise_floor, agent_volume * config.noise_agent_ratio) * rng.exponential(1.0)

        # fundamental 방향 편향: 괴리가 클수록 복원 압력 강함
        deviation = (price - fundamental) / fundamental if fundamental > 0 else 0.0
        reversion_prob = 1.0 / (1.0 + np.exp(-deviation * config.reversion_sigmoid_k))
        # reversion_prob > 0.5이면 가격이 fundamental 위 → sell 편향
        noise_side = "sell" if rng.random() < reversion_prob else "buy"

        orders.append(Order(agent_id=-1, side=noise_side, size=noise_size))

        # --- 주문 집계 ---
        net_buy = sum(o.size for o in orders if o.side == "buy")
        net_sell = sum(o.size for o in orders if o.side == "sell")
        net_flow = net_buy - net_sell
        total_volume = net_buy + net_sell

        # Kyle's lambda: 가격 변화율 = lambda * 순주문흐름 / 현재가격
        dp_pct = lambda_ * net_flow / max(price, config.tick_size)

        # Brock-Hommes 복원력: 비선형 (괴리 클수록 급격히 강해짐)
        reversion_pct = -deviation * abs(deviation) * config.reversion_strength

        # 합산 후 클리핑
        dp_pct = np.clip(dp_pct + reversion_pct, -config.dp_clip, config.dp_clip)

        # 노이즈 + stochastic volatility 증폭
        noise_pct = rng.normal(0, max(abs(dp_pct) * config.noise_dp_ratio, config.noise_dp_floor))
        # SV: 변동성이 높을 때 전체 가격 변동 증폭 (vol clustering 생성)
        sv_std = np.sqrt(max(sv_var, 1e-10))
        sv_multiplier = sv_std / max(config.sv_mean, 1e-6)
        dp = price * (dp_pct + noise_pct) * sv_multiplier

        # 봉 내 가격 경로 근사
        step_open = price
        step_high = max(price, price + abs(dp))
        step_low = min(price, price - abs(dp))

        price = max(config.tick_size, price + dp)
        step_close = price

        # high/low 보정
        step_high = max(step_high, step_close, step_open)
        step_low = min(step_low, step_close, step_open)

        # --- 이전 봉에서 대기 중인 청산 처리 (봉 간 분산) ---
        step_liq_count = 0
        if pending_liquidations:
            for aid in pending_liquidations:
                agent = agents[aid]
                if agent.is_liquidated or agent.position == 0:
                    continue
                liq_order = agent.liquidation_order()
                liq_flow = -liq_order.size if liq_order.side == "sell" else liq_order.size
                liq_pct = lambda_ * liq_flow / max(price, config.tick_size)
                liq_pct = np.clip(liq_pct, -config.liq_dp_clip, config.liq_dp_clip)
                price = max(config.tick_size, price * (1 + liq_pct))
                step_low = min(step_low, price)

                agent.apply_fill(liq_order.side, liq_order.size, price)
                agent.is_liquidated = True
                agent.position = 0.0
                agent.entry_price = 0.0
                step_liq_count += 1

                liquidation_log.append({
                    "step": step,
                    "agent_id": agent.agent_id,
                    "side": liq_order.side,
                    "size": liq_order.size,
                    "price": price,
                    "capital": agent.capital,
                    "realized_pnl": agent.realized_pnl,
                })
            pending_liquidations = []

        # --- 체결 처리 ---
        for order in orders:
            if order.agent_id == -1:
                continue
            agent = agents[order.agent_id]
            if not agent.is_liquidated:
                agent.apply_fill(order.side, order.size, price)

        # --- 청산 감지 → 다음 봉 큐 (즉시 처리 안 함) ---
        for agent in agents:
            if agent.is_liquidated or agent.position == 0:
                continue
            if agent.check_liquidation(price, config.liquidation_threshold):
                pending_liquidations.append(agent.agent_id)

        # --- 펀딩비 정산 ---
        if config.funding_interval > 0 and step > 0 and step % config.funding_interval == 0:
            for agent in agents:
                if agent.is_liquidated or agent.position == 0:
                    continue
                # 롱이 숏에게 지불 (funding_rate 양수일 때)
                payment = abs(agent.position) * price * funding_rate
                if agent.position > 0:
                    agent.realized_pnl -= payment
                else:
                    agent.realized_pnl += payment

        # --- Stochastic volatility 업데이트 (GARCH(1,1)) ---
        log_return = np.log(step_close / step_open) if step_open > 0 else 0.0
        sv_mean_var = config.sv_mean ** 2
        sv_var = (
            sv_mean_var * (1 - config.sv_persistence - config.sv_reaction)
            + config.sv_reaction * log_return ** 2
            + config.sv_persistence * sv_var
        )
        sv_var = max(sv_var, 1e-10)  # 바닥

        # --- 기록 ---
        price_history.append(step_close)
        return_history.append(log_return)
        volume_history.append(total_volume)

        cvd_cumulative += net_buy - net_sell

        ohlcv_rows.append({
            "open": step_open,
            "high": step_high,
            "low": step_low,
            "close": step_close,
            "volume": total_volume,
        })

        l3_rows.append({
            "funding_rate": funding_rate,
            "oi": oi_total,
            "oi_long_ratio": oi_long_ratio,
            "cvd": cvd_cumulative,
            "ls_ratio": total_long / total_short if total_short > 0 else float("inf"),
            "liquidation_count": step_liq_count,
        })

    # --- 결과 조립 ---
    ohlcv_df = pd.DataFrame(ohlcv_rows)
    l3_df = pd.DataFrame(l3_rows)

    # 에이전트 요약
    agent_rows = []
    for a in agents:
        agent_rows.append({
            "agent_id": a.agent_id,
            "capital": a.capital,
            "max_leverage": a.max_leverage,
            "info_level": a.info_level,
            "risk_tolerance": a.risk_tolerance,
            "herd_sensitivity": a.herd_sensitivity,
            "momentum_weight": a.momentum_weight,
            "mean_reversion_weight": a.mean_reversion_weight,
            "loss_aversion": a.loss_aversion,
            "reaction_speed": a.reaction_speed,
            "position_patience": a.position_patience,
            "final_position": a.position,
            "realized_pnl": a.realized_pnl,
            "is_liquidated": a.is_liquidated,
        })
    agent_df = pd.DataFrame(agent_rows)

    # 기본 통계
    returns = ohlcv_df["close"].pct_change().dropna()
    stats = {
        "final_price": float(ohlcv_df["close"].iloc[-1]),
        "total_return_pct": float(
            (ohlcv_df["close"].iloc[-1] / ohlcv_df["close"].iloc[0] - 1) * 100
        ),
        "volatility": float(returns.std()),
        "kurtosis": float(returns.kurtosis()) if len(returns) > 3 else 0.0,
        "max_drawdown_pct": _calc_max_drawdown(ohlcv_df["close"].values),
        "total_liquidations": len(liquidation_log),
        "agents_liquidated": int(agent_df["is_liquidated"].sum()),
        "agents_profitable": int((agent_df["realized_pnl"] > 0).sum()),
        "total_volume": float(ohlcv_df["volume"].sum()),
    }

    return SimResult(
        config=config,
        ohlcv=ohlcv_df,
        l3_data=l3_df,
        agent_summary=agent_df,
        liquidations=liquidation_log,
        stats=stats,
    )


def _calc_max_drawdown(prices: np.ndarray) -> float:
    """최대 낙폭 (%) 계산."""
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices[1:]:
        if p > peak:
            peak = p
        dd = (peak - p) / peak
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)

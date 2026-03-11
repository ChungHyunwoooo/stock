"""스캘핑 리스크 관리 모듈 — 데이터 기반 동적 SL/TP, 레버리지, 포지션 사이징.

기존 모듈 활용:
  - engine.strategy.risk.calculate_position_size() — 리스크 기반 수량 계산
  - engine.schema.RiskParams — 리스크 설정 스키마

핵심 원리:
  - ATR percentile rank (최근 분포에서 현재 위치) → SL/TP 배수 자동 보간
  - 고정 상수 없음: 설정은 범위(min/max)만, 실제 값은 시장 데이터가 결정
  - 변동성 높으면 SL 넓게 + 레버리지 낮게, 변동성 낮으면 SL 타이트 + 레버리지 높게
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.schema import RiskParams
from engine.strategy.risk import calculate_position_size

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScalpRiskConfig:
    """스캘핑 리스크 설정 — 범위만 지정, 실제 값은 데이터가 결정."""

    # ATR
    atr_period: int = 14
    atr_lookback: int = 100         # percentile rank 계산용 lookback 봉 수

    # SL 배수 범위 (ATR percentile → 선형 보간)
    sl_mult_min: float = 0.8        # 저변동성(pctile=0) 시 SL = ATR × 0.8
    sl_mult_max: float = 2.5        # 고변동성(pctile=1) 시 SL = ATR × 2.5

    # R:R 범위 (ATR percentile → 선형 보간)
    rr_min: float = 1.5             # 고변동성 시 R:R (추세 이용)
    rr_max: float = 3.0             # 저변동성 시 R:R (정밀 타겟)

    # 레버리지 조절
    leverage_min: int = 2
    leverage_max: int = 20

    # 포지션 사이징
    risk_per_trade_pct: float = 0.02  # 계좌 대비 거래당 리스크 (2%)
    max_position_pct: float = 0.1     # 계좌 대비 거래당 투입 비율 (10%)
    max_loss_pct: float = 0.5         # 투입금 대비 최대 손실 (50%) → lev × SL% < 이 값

    # SL/TP 범위 제한 (%) — 안전 클램프
    min_sl_pct: float = 0.1         # 최소 SL 0.1%
    max_sl_pct: float = 2.0         # 최대 SL 2.0%

    @classmethod
    def for_timeframe(cls, tf: str) -> ScalpRiskConfig:
        """타임프레임별 최적 프리셋 반환.

        - 1m/5m (스캘핑): 타이트 SL, 낮은 R:R
        - 15m/30m (데이트레이딩): 기본값
        - 1h/4h/1d (스윙): 넓은 SL, 높은 R:R
        - 미지 타임프레임: 데이트레이딩 (안전 기본값)
        """
        presets = {
            "1m": dict(sl_mult_min=0.5, sl_mult_max=1.5, rr_min=1.2, rr_max=2.5,
                       min_sl_pct=0.05, max_sl_pct=0.5),
            "5m": dict(sl_mult_min=0.5, sl_mult_max=1.5, rr_min=1.2, rr_max=2.5,
                       min_sl_pct=0.05, max_sl_pct=0.5),
            "1h": dict(sl_mult_min=1.5, sl_mult_max=4.0, rr_min=2.0, rr_max=5.0,
                       min_sl_pct=0.5, max_sl_pct=5.0),
            "4h": dict(sl_mult_min=1.5, sl_mult_max=4.0, rr_min=2.0, rr_max=5.0,
                       min_sl_pct=0.5, max_sl_pct=5.0),
            "1d": dict(sl_mult_min=1.5, sl_mult_max=4.0, rr_min=2.0, rr_max=5.0,
                       min_sl_pct=0.5, max_sl_pct=5.0),
        }
        # 15m/30m은 기본값 사용 (데이트레이딩)
        overrides = presets.get(tf, {})
        return cls(**overrides)


@dataclass(slots=True)
class ScalpRiskResult:
    """리스크 계산 결과."""

    stop_loss: float
    take_profit: float
    leverage: int
    quantity: float
    sl_pct: float           # SL 거리 (%)
    tp_pct: float           # TP 거리 (%)
    rr_ratio: float         # 실현 R:R 비율
    atr: float              # ATR 값
    atr_pct: float          # ATR / 현재가 (%)
    atr_pctile: float       # ATR percentile rank (0~1, 시장 변동성 위치)
    risk_amount: float      # 이 거래의 리스크 금액 (USDT)
    position_value: float   # 포지션 총 가치 (USDT)
    reason: str


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range 계산."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def calc_atr_percentile(atr_series: pd.Series, lookback: int = 100) -> float:
    """현재 ATR이 최근 lookback 봉 분포에서 어디에 위치하는지 (0~1).

    0 = 최근 중 가장 낮은 변동성, 1 = 최근 중 가장 높은 변동성.
    데이터가 lookback 미만이면 가용 데이터 전체 사용.
    """
    window = atr_series.iloc[-lookback:] if len(atr_series) >= lookback else atr_series
    current = float(atr_series.iloc[-1])

    if len(window) < 2:
        return 0.5  # 데이터 부족 시 중립

    # percentile rank: 현재 ATR보다 작은 값의 비율
    rank = float((window < current).sum()) / (len(window) - 1)
    return max(0.0, min(1.0, rank))


def _lerp(a: float, b: float, t: float) -> float:
    """선형 보간: t=0 → a, t=1 → b."""
    return a + (b - a) * t


def _price_precision(price: float) -> int:
    """가격 크기에 맞는 소수점 자릿수."""
    if price >= 1000:
        return 2
    if price >= 1:
        return 4
    if price >= 0.01:
        return 6
    return 8


def calculate_dynamic_sl_tp(
    entry_price: float,
    atr: float,
    atr_pctile: float,
    side: str,
    config: ScalpRiskConfig | None = None,
) -> tuple[float, float, float, float]:
    """ATR percentile 기반 동적 SL/TP 계산.

    ATR percentile이 높을수록(변동성 큼):
      - SL 배수 올림 (넓게 잡아서 whipsaw 방지)
      - R:R 낮춤 (추세에서 빨리 익절)
    ATR percentile이 낮을수록(변동성 작음):
      - SL 배수 내림 (타이트하게)
      - R:R 높임 (정밀 타겟)

    Returns:
        (stop_loss, take_profit, sl_pct, tp_pct)
    """
    cfg = config or ScalpRiskConfig()

    # percentile → SL 배수 (선형 보간)
    sl_mult = _lerp(cfg.sl_mult_min, cfg.sl_mult_max, atr_pctile)

    # percentile → R:R (고변동성일수록 R:R 낮춤)
    rr_ratio = _lerp(cfg.rr_max, cfg.rr_min, atr_pctile)

    sl_distance = atr * sl_mult
    tp_distance = sl_distance * rr_ratio

    # SL 범위 안전 클램프
    sl_pct = sl_distance / entry_price * 100
    sl_pct = max(cfg.min_sl_pct, min(cfg.max_sl_pct, sl_pct))
    sl_distance = entry_price * sl_pct / 100

    # TP도 클램프된 SL 기준으로 재계산 (R:R 비율 유지)
    tp_distance = sl_distance * rr_ratio
    tp_pct = tp_distance / entry_price * 100

    if side == "long":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    prec = _price_precision(entry_price)
    return round(sl, prec), round(tp, prec), round(sl_pct, 4), round(tp_pct, 4)


def calculate_dynamic_leverage(
    atr_pct: float,
    atr_pctile: float,
    config: ScalpRiskConfig | None = None,
) -> int:
    """변동성 기반 레버리지 계산.

    ATR percentile → 레버리지 역보간.
    고변동성(pctile=1) → leverage_min, 저변동성(pctile=0) → leverage_max.
    """
    cfg = config or ScalpRiskConfig()

    if atr_pct <= 0:
        return cfg.leverage_min

    # percentile 역보간: 변동성 높을수록 레버리지 낮게
    raw_leverage = _lerp(cfg.leverage_max, cfg.leverage_min, atr_pctile)
    leverage = int(max(cfg.leverage_min, min(cfg.leverage_max, raw_leverage)))
    return leverage


def fractional_kelly(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 0.25,
) -> float:
    """Fractional Kelly Criterion 포지션 사이징.

    Kelly% = W - (1-W)/R  (W=승률, R=avg_win/avg_loss)
    Fractional Kelly = Kelly% × fraction (과적합 방지)

    Args:
        win_rate: 승률 (0~1)
        avg_win: 평균 이익 (절대값)
        avg_loss: 평균 손실 (절대값, 양수)
        fraction: Kelly 비율 (0.25 = Quarter Kelly)

    Returns:
        자본 대비 투입 비율 (0~1). 음수면 0 반환 (진입 불가 시장).
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0
    r = avg_win / avg_loss  # payoff ratio
    kelly = win_rate - (1 - win_rate) / r
    if kelly <= 0:
        return 0.0
    return min(kelly * fraction, 1.0)


def calculate_scalp_risk(
    df: pd.DataFrame,
    entry_price: float,
    side: str,
    capital: float,
    config: ScalpRiskConfig | None = None,
    kelly_fraction: float | None = None,
    trade_stats: dict | None = None,
) -> ScalpRiskResult:
    """종합 스캘핑 리스크 계산 — 모든 파라미터가 데이터 기반.

    Args:
        df: OHLCV DataFrame (ATR 계산용)
        entry_price: 진입 가격
        side: "long" 또는 "short"
        capital: 가용 자본 (USDT)
        config: 리스크 범위 설정
        kelly_fraction: Kelly 비율 (None이면 미사용, 0.25=Quarter Kelly)
        trade_stats: {"win_rate": 0.6, "avg_win": 1.5, "avg_loss": 1.0} — Kelly 계산용

    Returns:
        ScalpRiskResult
    """
    cfg = config or ScalpRiskConfig()

    # 1. ATR + percentile rank
    atr_series = calc_atr(df, cfg.atr_period)
    atr = float(atr_series.iloc[-1])
    atr_pct = atr / entry_price * 100
    atr_pctile = calc_atr_percentile(atr_series, cfg.atr_lookback)

    # 2. 동적 SL/TP (percentile 기반)
    sl, tp, sl_pct, tp_pct = calculate_dynamic_sl_tp(
        entry_price, atr, atr_pctile, side, cfg,
    )

    # 3. 동적 레버리지 (percentile 기반)
    leverage = calculate_dynamic_leverage(atr_pct, atr_pctile, cfg)

    # 3-1. 안전 제한: leverage × SL% < max_loss_pct (투입금 대비 최대 손실)
    if sl_pct > 0:
        max_leverage_by_sl = int(cfg.max_loss_pct * 100 / sl_pct)
        max_leverage_by_sl = max(cfg.leverage_min, max_leverage_by_sl)
        if leverage > max_leverage_by_sl:
            leverage = max_leverage_by_sl

    # 4. 포지션 사이징
    # Kelly Criterion 사용 가능 시 투입 비율 조정
    effective_risk_pct = cfg.risk_per_trade_pct
    if kelly_fraction is not None and trade_stats:
        kelly_pct = fractional_kelly(
            win_rate=trade_stats.get("win_rate", 0.5),
            avg_win=trade_stats.get("avg_win", 1.0),
            avg_loss=trade_stats.get("avg_loss", 1.0),
            fraction=kelly_fraction,
        )
        if kelly_pct > 0:
            effective_risk_pct = kelly_pct  # cap 제거 — RiskManager.position_size_factor()가 드로다운 시 축소
            logger.info("Kelly 사이징: %.2f%% (원래 %.2f%%)", kelly_pct * 100, cfg.risk_per_trade_pct * 100)

    risk_params = RiskParams(
        stop_loss_pct=sl_pct / 100,
        take_profit_pct=tp_pct / 100,
        risk_per_trade_pct=effective_risk_pct,
    )
    quantity = calculate_position_size(capital, risk_params, entry_price, sl)

    # 포지션 크기 제한
    position_value = quantity * entry_price
    max_position = capital * cfg.max_position_pct * leverage
    if position_value > max_position:
        quantity = max_position / entry_price
        position_value = quantity * entry_price

    # 5. R:R 비율
    rr_ratio = tp_pct / sl_pct if sl_pct > 0 else 0

    # 6. 리스크 금액
    risk_amount = abs(entry_price - sl) * quantity

    reason_parts = [
        f"ATR={atr:.2f}({atr_pct:.3f}% p{atr_pctile:.0%})",
        f"SL={sl_pct:.2f}% TP={tp_pct:.2f}%",
        f"R:R=1:{rr_ratio:.1f}",
        f"레버리지={leverage}x",
        f"리스크=${risk_amount:.2f}({cfg.risk_per_trade_pct*100:.1f}%)",
    ]

    return ScalpRiskResult(
        stop_loss=sl,
        take_profit=tp,
        leverage=leverage,
        quantity=round(quantity, 4),
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        rr_ratio=round(rr_ratio, 2),
        atr=round(atr, 4),
        atr_pct=round(atr_pct, 4),
        atr_pctile=round(atr_pctile, 4),
        risk_amount=round(risk_amount, 4),
        position_value=round(position_value, 4),
        reason=" | ".join(reason_parts),
    )

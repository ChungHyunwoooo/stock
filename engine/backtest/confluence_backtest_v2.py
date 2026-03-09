"""Confluence 전략 v2 백테스트 — 멀티TF 아키텍처 (D1/4H 방향 + 1H 스코어링 + 5m 진입).

Two-pass 구조:
  1차: 1H 봉 스캔 → confluence score >= threshold 이면 "armed"
  2차: armed 신호마다 후속 5m 봉에서 진입 트리거 탐색
       - EMA21 pullback + close confirmation
       - 또는 engulfing 캔들
  SL: 5m 구조 기반 (최근 6봉 swing low/high), 최소 0.15%
  TP: R-multiple (SL 거리 × tp_ratio)
  Armed 유효기간: 12 1H봉 (12시간) 이내 트리거 미발생 시 만료
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import talib

from engine.analysis import build_context
from engine.analysis.confluence import calc_confluence_score
from engine.analysis.mtf_confluence import calc_mtf_confluence
from engine.data.base import get_provider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConfluenceTradeV2:
    entry_date: str
    exit_date: str
    side: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "TP", "SL", "TIME", "END"
    pnl_pct: float
    confluence_score: int
    funding_point: bool
    mtf_point: bool
    vp_point: bool
    market_regime: str  # "BULL", "BEAR", "RANGE"
    armed_date: str  # 1H 신호 armed 시각
    entry_tf_sl_pct: float  # 5m 구조 기반 SL %


@dataclass
class ConfluenceBacktestResultV2:
    symbol: str
    scoring_tf: str
    entry_tf: str
    start_date: str
    end_date: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_confluence_score: float
    trades: list[ConfluenceTradeV2] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    score_distribution: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Armed signal container
# ---------------------------------------------------------------------------

@dataclass
class _ArmedSignal:
    armed_idx: int  # 1H bar index
    armed_date: str
    side: str
    score: int
    funding_point: bool
    mtf_point: bool
    vp_point: bool
    regime: str
    bar_ts: pd.Timestamp  # 1H bar timestamp
    expiry_ts: pd.Timestamp  # armed + max_armed_bars * 1H


# ---------------------------------------------------------------------------
# Helpers (reused from v1)
# ---------------------------------------------------------------------------

def _tf_to_timedelta(tf: str) -> pd.Timedelta:
    mapping = {
        "1m": pd.Timedelta(minutes=1),
        "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15),
        "30m": pd.Timedelta(minutes=30),
        "1h": pd.Timedelta(hours=1),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
    }
    return mapping.get(tf, pd.Timedelta(hours=4))


def _tf_to_hours(tf: str) -> float:
    mapping = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5, "1h": 1, "4h": 4, "1d": 24}
    return mapping.get(tf, 4)


def _build_funding_index(funding_map: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    if not funding_map:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    sorted_items = sorted(funding_map.items())
    ts_arr = np.array([t for t, _ in sorted_items], dtype=np.int64)
    rate_arr = np.array([r for _, r in sorted_items], dtype=np.float64)
    return ts_arr, rate_arr


def _lookup_funding(ts_arr: np.ndarray, rate_arr: np.ndarray, bar_ts_ms: int) -> float:
    if len(ts_arr) == 0:
        return 0.0
    idx = int(np.searchsorted(ts_arr, bar_ts_ms, side="right")) - 1
    if idx < 0:
        return 0.0
    diff = bar_ts_ms - int(ts_arr[idx])
    if diff <= 28800000:  # 8h
        return float(rate_arr[idx])
    return 0.0


# ---------------------------------------------------------------------------
# 5m entry trigger helpers
# ---------------------------------------------------------------------------

def _calc_ema(series: np.ndarray, period: int) -> np.ndarray:
    """talib EMA wrapper."""
    return talib.EMA(series.astype(np.float64), timeperiod=period)


def _check_ema21_pullback(df_5m: pd.DataFrame, side: str) -> tuple[bool, int]:
    """EMA21 pullback + close confirmation on 5m.

    LONG: 가격이 EMA21 아래로 pullback 후 EMA21 위로 close
    SHORT: 가격이 EMA21 위로 rally 후 EMA21 아래로 close

    Returns:
        (triggered, bar_index) — bar_index is the trigger bar in df_5m
    """
    if len(df_5m) < 22:
        return False, -1

    close = df_5m["close"].values.astype(np.float64)
    low = df_5m["low"].values.astype(np.float64)
    high = df_5m["high"].values.astype(np.float64)
    ema21 = _calc_ema(close, 21)

    for i in range(22, len(df_5m)):
        if np.isnan(ema21[i]) or np.isnan(ema21[i - 1]):
            continue

        if side == "LONG":
            # 이전 봉에서 low가 EMA21 이하 (pullback), 현재 봉에서 close > EMA21
            if low[i - 1] <= ema21[i - 1] and close[i] > ema21[i]:
                return True, i
        else:  # SHORT
            # 이전 봉에서 high가 EMA21 이상 (rally), 현재 봉에서 close < EMA21
            if high[i - 1] >= ema21[i - 1] and close[i] < ema21[i]:
                return True, i

    return False, -1


def _check_engulfing(df_5m: pd.DataFrame, side: str) -> tuple[bool, int]:
    """5m engulfing candle in signal direction.

    Returns:
        (triggered, bar_index)
    """
    if len(df_5m) < 3:
        return False, -1

    o = df_5m["open"].values.astype(np.float64)
    c = df_5m["close"].values.astype(np.float64)
    h = df_5m["high"].values.astype(np.float64)
    lw = df_5m["low"].values.astype(np.float64)

    for i in range(1, len(df_5m)):
        prev_body = abs(c[i - 1] - o[i - 1])
        curr_body = abs(c[i] - o[i])

        if curr_body <= prev_body:
            continue

        if side == "LONG":
            # Bullish engulfing: 이전 봉 음봉, 현재 봉 양봉이 이전을 감싸
            if c[i - 1] < o[i - 1] and c[i] > o[i]:
                if c[i] > o[i - 1] and o[i] < c[i - 1]:
                    return True, i
        else:  # SHORT
            # Bearish engulfing
            if c[i - 1] > o[i - 1] and c[i] < o[i]:
                if c[i] < o[i - 1] and o[i] > c[i - 1]:
                    return True, i

    return False, -1


def _find_5m_trigger(df_5m: pd.DataFrame, side: str) -> tuple[bool, int]:
    """Find entry trigger on 5m data. Try EMA21 pullback first, then engulfing."""
    triggered, idx = _check_ema21_pullback(df_5m, side)
    if triggered:
        return True, idx

    triggered, idx = _check_engulfing(df_5m, side)
    if triggered:
        return True, idx

    return False, -1


def _calc_5m_sl(df_5m: pd.DataFrame, trigger_idx: int, side: str, entry_price: float,
                min_sl_pct: float = 0.0015) -> float:
    """5m 구조 기반 SL 계산.

    LONG SL: 최근 6봉(30분) swing low 아래
    SHORT SL: 최근 6봉(30분) swing high 위
    최소 SL: entry_price * min_sl_pct
    """
    lookback = 6
    start = max(0, trigger_idx - lookback)

    if side == "LONG":
        swing_low = float(df_5m["low"].iloc[start:trigger_idx + 1].min())
        sl = swing_low
        min_sl_dist = entry_price * min_sl_pct
        if entry_price - sl < min_sl_dist:
            sl = entry_price - min_sl_dist
    else:  # SHORT
        swing_high = float(df_5m["high"].iloc[start:trigger_idx + 1].max())
        sl = swing_high
        min_sl_dist = entry_price * min_sl_pct
        if sl - entry_price < min_sl_dist:
            sl = entry_price + min_sl_dist

    return sl


# ---------------------------------------------------------------------------
# Main backtest function
# ---------------------------------------------------------------------------

def run_confluence_backtest_v2(
    symbol: str = "BTC/USDT",
    start: str = "2023-03-01",
    end: str = "2025-03-01",
    scoring_tf: str = "1h",
    entry_tf: str = "5m",
    lookback_bars: int = 300,
    initial_capital: float = 10_000.0,
    leverage: int = 3,
    risk_pct: float = 0.01,
    min_score: int = 2,
    min_score_short: int = 3,
    tp_ratio: float = 2.0,
    max_armed_bars: int = 12,
    max_hold_bars: int = 144,  # 5m 봉 기준 (12시간)
    adx_threshold: int = 25,
    mtf_threshold_long: float = 0.55,
    mtf_threshold_short: float = 0.70,
    fee_rate: float = 0.0004,
    funding_sim_mean: float = 0.0001,
    funding_sim_std: float = 0.0008,
    use_real_funding: bool = True,
    funding_data_path: str | None = None,
) -> ConfluenceBacktestResultV2:
    """Confluence v2 백테스트 실행 — 멀티TF 아키텍처.

    1차 패스: 1H 봉에서 confluence score >= threshold 인 armed 신호 수집
    2차 패스: armed 신호별 5m 봉에서 진입 트리거 탐색 + 트레이드 시뮬레이션
    """
    # --- 데이터 로드 ---
    provider = get_provider("crypto_spot", exchange="binance")
    mtf_tfs = {"1d": "1d", "4h": "4h", "1h": "1h"}

    frames: dict[str, pd.DataFrame] = {}
    for tf_key, tf_val in mtf_tfs.items():
        delta = _tf_to_timedelta(tf_val)
        tf_start = (pd.Timestamp(start) - delta * lookback_bars).strftime("%Y-%m-%d")
        try:
            df = provider.fetch_ohlcv(symbol, tf_start, end, tf_val)
            if not df.empty:
                frames[tf_key] = df
        except Exception as e:
            logger.warning("Failed to fetch %s %s: %s", symbol, tf_val, e)

    if scoring_tf not in frames:
        raise ValueError(f"Scoring TF '{scoring_tf}' data not available")

    scoring_df = frames[scoring_tf]

    # D1 EMA200 계산
    d1_ema200 = None
    if "1d" in frames and len(frames["1d"]) >= 200:
        d1_close = frames["1d"]["close"].values.astype(np.float64)
        d1_ema200 = talib.EMA(d1_close, timeperiod=200)

    # 백테스트 시작 인덱스
    start_ts = pd.Timestamp(start, tz="UTC")
    mask = scoring_df.index >= start_ts
    if not mask.any():
        raise ValueError(f"No data after {start}")
    start_idx = int(mask.argmax())
    if start_idx < 50:
        start_idx = 50

    # --- 펀딩비 데이터 ---
    funding_map: dict[int, float] = {}
    real_funding_loaded = False

    if use_real_funding:
        if funding_data_path is None:
            from engine.config_path import config_file
            funding_data_path = str(config_file("funding_rate_history.json"))
        fp = Path(funding_data_path)
        if fp.exists():
            with open(fp) as f:
                all_funding = json.load(f)
            sym_key = None
            for k in all_funding:
                if symbol.split(":")[0] in k:
                    sym_key = k
                    break
            if sym_key and all_funding[sym_key]:
                for rec in all_funding[sym_key]:
                    funding_map[int(rec["timestamp"])] = float(rec["rate"])
                real_funding_loaded = True
                logger.info("Real funding loaded: %s, %d records", sym_key, len(funding_map))

    if not real_funding_loaded:
        np.random.seed(42)
        n_bars = len(scoring_df)
        sim_rates = np.random.normal(funding_sim_mean, funding_sim_std, n_bars)
        extreme_mask = np.random.random(n_bars) < 0.10
        sim_rates[extreme_mask] = np.random.choice(
            [-0.002, -0.001, 0.002, 0.003, 0.005], size=extreme_mask.sum()
        )
        for idx_i in range(n_bars):
            ts = int(scoring_df.index[idx_i].timestamp() * 1000)
            funding_map[ts] = float(sim_rates[idx_i])

    funding_ts_arr, funding_rate_arr = _build_funding_index(funding_map)

    # ===================================================================
    # 1차 패스: 1H 봉 스캔 → armed 신호 수집
    # ===================================================================
    armed_signals: list[_ArmedSignal] = []
    score_dist: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    # 매 4봉(4시간) 간격으로 스캔 — 17,000→4,250봉으로 감소
    scan_step = 4
    # 최근 armed 시각 추적 (중복 armed 방지: 12시간 이내 재armed 금지)
    last_armed_ts: pd.Timestamp | None = None

    for i in range(start_idx, len(scoring_df), scan_step):
        bar = scoring_df.iloc[i]
        bar_ts = scoring_df.index[i]
        bar_close = float(bar["close"])
        bar_date = str(bar_ts)[:19]

        # 중복 armed 방지 (12시간 이내)
        if last_armed_ts is not None and bar_ts < last_armed_ts + pd.Timedelta(hours=12):
            continue

        # D1 EMA200 방향 필터
        if d1_ema200 is not None and "1d" in frames:
            # 현재 1H 봉 시점의 D1 봉 찾기
            d1_df = frames["1d"]
            d1_mask = d1_df.index <= bar_ts
            if d1_mask.any():
                d1_idx = int(d1_mask.sum()) - 1
                if d1_idx >= 200 and not np.isnan(d1_ema200[d1_idx]):
                    d1_close_val = float(d1_df["close"].iloc[d1_idx])
                    ema200_val = float(d1_ema200[d1_idx])
                    if d1_close_val > ema200_val:
                        allowed_side = "LONG"
                    else:
                        allowed_side = "SHORT"
                else:
                    allowed_side = None  # 데이터 부족 → 양방향 허용
            else:
                allowed_side = None
        else:
            allowed_side = None

        # 슬라이스 프레임 — scoring_tf만 build_context, 나머지는 MTF용으로 경량 슬라이스
        scoring_sliced = scoring_df.iloc[:i + 1]
        if len(scoring_sliced) < 50:
            continue

        ctx = build_context(scoring_sliced.tail(200))  # 최근 200봉만으로 충분

        # MTF용 슬라이스 (경량)
        slice_frames: dict[str, pd.DataFrame] = {scoring_tf: scoring_sliced.tail(200)}
        for tf_key, tf_df in frames.items():
            if tf_key == scoring_tf:
                continue
            sliced = tf_df[tf_df.index <= bar_ts]
            if len(sliced) >= 50:
                slice_frames[tf_key] = sliced.tail(200)
        trend = ctx["structure"].get("trend", "RANGING")

        if trend == "BULLISH":
            side_str = "LONG"
        elif trend == "BEARISH":
            side_str = "SHORT"
        else:
            continue

        # D1 EMA200 방향 필터 적용
        if allowed_side is not None and side_str != allowed_side:
            continue

        # MTF confluence
        mtf_result = calc_mtf_confluence(slice_frames, side_str)
        mtf_score_val = mtf_result["score"]

        # MTF threshold 체크 (LONG/SHORT 별도)
        if side_str == "LONG" and mtf_score_val < mtf_threshold_long:
            continue
        if side_str == "SHORT" and mtf_score_val < mtf_threshold_short:
            continue

        # VPVR
        vpvr = ctx["volume"].get("vpvr", {})
        adx_val = ctx["adx"].get("adx", 0)

        # 펀딩비
        bar_ts_ms = int(bar_ts.timestamp() * 1000)
        fr = _lookup_funding(funding_ts_arr, funding_rate_arr, bar_ts_ms)

        hour_utc = bar_ts.hour if hasattr(bar_ts, "hour") else 12

        confluence = calc_confluence_score(
            funding_rate=fr,
            mtf_score=mtf_score_val,
            vpvr=vpvr,
            side=side_str,
            adx_val=adx_val,
            current_hour_utc=hour_utc,
        )

        score = confluence["total_score"]
        score_dist[score] = score_dist.get(score, 0) + 1

        # ADX threshold 적용 (v2: 25로 상향)
        if adx_val < adx_threshold:
            continue

        # 방향별 최소 점수
        required_score = min_score if side_str == "LONG" else min_score_short
        if not confluence["execute"] or score < required_score:
            continue

        # 레짐 판단 — D1 EMA200 방향으로 간소화 (build_context 재호출 회피)
        if allowed_side == "LONG":
            regime = "BULL"
        elif allowed_side == "SHORT":
            regime = "BEAR"
        else:
            regime = "RANGE"

        expiry_ts = bar_ts + pd.Timedelta(hours=max_armed_bars)

        armed_signals.append(_ArmedSignal(
            armed_idx=i,
            armed_date=bar_date,
            side=side_str,
            score=score,
            funding_point=confluence["funding_point"],
            mtf_point=confluence["mtf_point"],
            vp_point=confluence["vp_point"],
            regime=regime,
            bar_ts=bar_ts,
            expiry_ts=expiry_ts,
        ))
        last_armed_ts = bar_ts

    print(f"    1차 패스 완료: {len(armed_signals)} armed 신호 (스캔 {(len(scoring_df)-start_idx)//scan_step}봉)", flush=True)

    # ===================================================================
    # 2차 패스: armed 신호별 5m 데이터 조회 + 트리거 + 트레이드 시뮬레이션
    # ===================================================================
    trades: list[ConfluenceTradeV2] = []
    equity_val = initial_capital
    equity: list[float] = [initial_capital]

    # 이전 트레이드 종료 시각 추적 (중복 진입 방지)
    last_exit_ts: pd.Timestamp | None = None

    for sig in armed_signals:
        # 이전 트레이드와 겹치면 스킵
        if last_exit_ts is not None and sig.bar_ts < last_exit_ts:
            continue

        # 5m 데이터 fetch (armed window: armed_ts ~ expiry_ts)
        fetch_start = (sig.bar_ts - pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        fetch_end = sig.expiry_ts.strftime("%Y-%m-%d %H:%M:%S")

        try:
            df_5m = provider.fetch_ohlcv(symbol, fetch_start, fetch_end, entry_tf)
        except Exception as e:
            logger.warning("Failed to fetch 5m for %s at %s: %s", symbol, sig.armed_date, e)
            continue

        if df_5m is None or df_5m.empty or len(df_5m) < 22:
            continue

        # armed 시각 이후의 5m 봉만
        df_5m_window = df_5m[df_5m.index > sig.bar_ts]
        if len(df_5m_window) < 3:
            continue

        # EMA21 계산을 위해 armed 이전 봉도 포함해 전달
        # (EMA warmup을 위해 전체 df_5m 사용, 하지만 trigger는 window 내에서만)
        triggered, trig_idx_in_full = _find_5m_trigger(df_5m, sig.side)

        if not triggered or trig_idx_in_full < 0:
            continue

        # trigger가 armed window 밖이면 스킵
        trig_ts = df_5m.index[trig_idx_in_full]
        if trig_ts <= sig.bar_ts or trig_ts > sig.expiry_ts:
            continue

        entry_price = float(df_5m["close"].iloc[trig_idx_in_full])
        entry_date = str(trig_ts)[:19]

        # SL 계산 (5m 구조 기반)
        sl_price = _calc_5m_sl(df_5m, trig_idx_in_full, sig.side, entry_price)

        if sig.side == "LONG":
            sl_dist = entry_price - sl_price
        else:
            sl_dist = sl_price - entry_price

        sl_pct = sl_dist / entry_price

        # TP 계산 (R-multiple)
        if sig.side == "LONG":
            tp_price = entry_price + sl_dist * tp_ratio
        else:
            tp_price = entry_price - sl_dist * tp_ratio

        # --- 트레이드 시뮬레이션 (5m 봉 순회) ---
        exit_reason = None
        exit_price = entry_price
        exit_date = entry_date
        bars_held = 0

        for j in range(trig_idx_in_full + 1, len(df_5m)):
            bars_held += 1
            bar_5m = df_5m.iloc[j]
            bh = float(bar_5m["high"])
            bl = float(bar_5m["low"])
            bc = float(bar_5m["close"])

            # SL 체크
            if sig.side == "LONG" and bl <= sl_price:
                exit_reason = "SL"
                exit_price = sl_price
                exit_date = str(df_5m.index[j])[:19]
                break
            elif sig.side == "SHORT" and bh >= sl_price:
                exit_reason = "SL"
                exit_price = sl_price
                exit_date = str(df_5m.index[j])[:19]
                break

            # TP 체크
            if sig.side == "LONG" and bh >= tp_price:
                exit_reason = "TP"
                exit_price = tp_price
                exit_date = str(df_5m.index[j])[:19]
                break
            elif sig.side == "SHORT" and bl <= tp_price:
                exit_reason = "TP"
                exit_price = tp_price
                exit_date = str(df_5m.index[j])[:19]
                break

            # 시간 제한
            if bars_held >= max_hold_bars:
                exit_reason = "TIME"
                exit_price = bc
                exit_date = str(df_5m.index[j])[:19]
                break

        # 5m 데이터 내에서 청산 안 된 경우
        if exit_reason is None:
            exit_reason = "END"
            exit_price = float(df_5m["close"].iloc[-1])
            exit_date = str(df_5m.index[-1])[:19]

        # PnL 계산
        if sig.side == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price

        pnl_pct -= fee_rate * 2  # 진입+청산 수수료
        pnl_pct *= leverage

        equity_val *= (1 + pnl_pct * risk_pct)
        equity_val = max(equity_val, 0)
        equity.append(equity_val)

        trades.append(ConfluenceTradeV2(
            entry_date=entry_date,
            exit_date=exit_date,
            side=sig.side,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pct=round(pnl_pct * 100, 2),
            confluence_score=sig.score,
            funding_point=sig.funding_point,
            mtf_point=sig.mtf_point,
            vp_point=sig.vp_point,
            market_regime=sig.regime,
            armed_date=sig.armed_date,
            entry_tf_sl_pct=round(sl_pct * 100, 4),
        ))

        # 중복 진입 방지: 이 트레이드 종료 시각 기록 (tz-aware로 통일)
        last_exit_ts = pd.Timestamp(exit_date, tz="UTC")

    # --- 메트릭 계산 ---
    pnls = [t.pnl_pct for t in trades]
    win_list = [p for p in pnls if p > 0]
    loss_list = [p for p in pnls if p <= 0]

    win_rate = len(win_list) / len(pnls) if pnls else 0.0
    avg_win = sum(win_list) / len(win_list) if win_list else 0.0
    avg_loss = sum(loss_list) / len(loss_list) if loss_list else 0.0

    gross_profit = sum(win_list) if win_list else 0.0
    gross_loss = abs(sum(loss_list)) if loss_list else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    eq_series = pd.Series(equity, dtype=float)
    total_return = (equity[-1] / initial_capital - 1) * 100 if equity else 0.0

    # Max drawdown
    if len(eq_series) >= 2:
        rolling_max = eq_series.cummax()
        dd = (eq_series - rolling_max) / rolling_max
        max_dd = float(dd.min()) * 100
    else:
        max_dd = 0.0

    # Sharpe (연간화)
    sharpe: float | None = None
    if len(pnls) >= 2:
        pnl_series = pd.Series(pnls, dtype=float)
        if pnl_series.std() > 0:
            # 5m 진입이지만 트레이드 빈도 기반 연간화
            trades_per_year = len(pnls) / 2  # 2년 백테스트 기준
            sharpe = float(pnl_series.mean() / pnl_series.std() * math.sqrt(trades_per_year))

    avg_score = sum(t.confluence_score for t in trades) / len(trades) if trades else 0.0

    return ConfluenceBacktestResultV2(
        symbol=symbol,
        scoring_tf=scoring_tf,
        entry_tf=entry_tf,
        start_date=start,
        end_date=end,
        total_trades=len(trades),
        wins=len(win_list),
        losses=len(loss_list),
        win_rate=round(win_rate * 100, 1),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        total_return_pct=round(total_return, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=round(sharpe, 2) if sharpe else None,
        avg_confluence_score=round(avg_score, 2),
        trades=trades,
        equity_curve=equity,
        score_distribution=score_dist,
    )

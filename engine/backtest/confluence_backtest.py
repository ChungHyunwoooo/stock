"""Confluence 전략 백테스트 — 멀티TF + 점수 기반 선물 시뮬레이션.

실제 과거 OHLCV 데이터로 confluence 파이프라인을 시뮬레이션.
펀딩비는 시뮬레이션 (실제 과거 데이터 없이 랜덤 분포).
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


@dataclass
class ConfluenceTrade:
    entry_date: str
    exit_date: str
    side: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "TP1", "TP2", "TP3", "SL", "TIME", "END"
    pnl_pct: float
    confluence_score: int
    funding_point: bool
    mtf_point: bool
    vp_point: bool
    market_regime: str  # "BULL", "BEAR", "RANGE" — 진입 시점 D1 트렌드 기반


@dataclass
class ConfluenceBacktestResult:
    symbol: str
    timeframe: str
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
    trades: list[ConfluenceTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    score_distribution: dict[int, int] = field(default_factory=dict)


def run_confluence_backtest(
    symbol: str = "BTC/USDT",
    start: str = "2024-06-01",
    end: str = "2025-03-01",
    entry_tf: str = "4h",
    lookback_bars: int = 300,
    initial_capital: float = 10_000.0,
    leverage: int = 3,
    risk_pct: float = 0.01,
    min_score: int = 2,
    atr_sl_mult: float = 1.5,
    tp_ratios: list[float] | None = None,
    max_hold_bars: int = 30,
    funding_sim_mean: float = 0.0001,
    funding_sim_std: float = 0.0008,
    fee_rate: float = 0.0004,  # taker 0.04% × 2 (진입+청산)
    use_real_funding: bool = True,
    funding_data_path: str | None = None,
) -> ConfluenceBacktestResult:
    """Confluence 전략 백테스트 실행.

    Args:
        symbol: 심볼
        start/end: 백테스트 기간
        entry_tf: 진입 타임프레임 (4h 권장)
        lookback_bars: OHLCV 조회 봉 수
        initial_capital: 초기 자본
        leverage: 레버리지
        risk_pct: 거래당 리스크 비율
        min_score: 최소 confluence 점수
        atr_sl_mult: ATR SL 배수
        tp_ratios: TP R배수 리스트
        max_hold_bars: 최대 보유 봉 수 (시간제한 청산)
        funding_sim_mean/std: 펀딩비 시뮬레이션 파라미터
        use_real_funding: 실제 펀딩비 데이터 사용 여부
        funding_data_path: 펀딩비 JSON 파일 경로
    """
    if tp_ratios is None:
        tp_ratios = [1.0, 1.5, 2.5]

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

    if entry_tf not in frames:
        raise ValueError(f"Entry TF '{entry_tf}' data not available")

    entry_df = frames[entry_tf]

    # 백테스트 시작 인덱스 (lookback 이후부터)
    start_ts = pd.Timestamp(start, tz="UTC")
    mask = entry_df.index >= start_ts
    if not mask.any():
        raise ValueError(f"No data after {start}")

    start_idx = int(mask.argmax())
    if start_idx < 50:
        start_idx = 50  # 최소 50봉 워밍업

    # --- 펀딩비 데이터 ---
    funding_map: dict[int, float] = {}  # unix_ms -> rate
    real_funding_loaded = False

    if use_real_funding:
        if funding_data_path is None:
            funding_data_path = str(
                Path(__file__).resolve().parent.parent.parent / "config" / "funding_rate_history.json"
            )
        fp = Path(funding_data_path)
        if fp.exists():
            with open(fp) as f:
                all_funding = json.load(f)
            # symbol key: "BTC/USDT" or "BTC/USDT:USDT" 등 유연 매칭
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
        # 시뮬레이션 폴백
        np.random.seed(42)
        n_bars = len(entry_df)
        sim_rates = np.random.normal(funding_sim_mean, funding_sim_std, n_bars)
        extreme_mask = np.random.random(n_bars) < 0.10
        sim_rates[extreme_mask] = np.random.choice(
            [-0.002, -0.001, 0.002, 0.003, 0.005], size=extreme_mask.sum()
        )
        for idx_i in range(n_bars):
            ts = int(entry_df.index[idx_i].timestamp() * 1000)
            funding_map[ts] = float(sim_rates[idx_i])

    # 정렬된 인덱스 구축 (O(log n) 조회용)
    funding_ts_arr, funding_rate_arr = _build_funding_index(funding_map)

    # --- 시뮬레이션 ---
    capital = initial_capital
    trades: list[ConfluenceTrade] = []
    equity: list[float] = []
    score_dist: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    in_position = False
    pos_side = ""
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tps: list[float] = []
    pos_entry_date = ""
    pos_bars = 0
    pos_score = 0
    pos_funding = False
    pos_mtf = False
    pos_vp = False

    for i in range(start_idx, len(entry_df)):
        bar = entry_df.iloc[i]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        bar_close = float(bar["close"])
        bar_date = str(entry_df.index[i])[:19]

        # --- 포지션 관리 ---
        if in_position:
            pos_bars += 1
            exit_reason = None
            exit_price = bar_close

            # SL 체크
            if pos_side == "LONG" and bar_low <= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl
            elif pos_side == "SHORT" and bar_high >= pos_sl:
                exit_reason = "SL"
                exit_price = pos_sl

            # TP 체크 (첫번째 TP만 — 단순화)
            if exit_reason is None and pos_tps:
                if pos_side == "LONG" and bar_high >= pos_tps[0]:
                    exit_reason = "TP1"
                    exit_price = pos_tps[0]
                elif pos_side == "SHORT" and bar_low <= pos_tps[0]:
                    exit_reason = "TP1"
                    exit_price = pos_tps[0]

            # 시간 제한
            if exit_reason is None and pos_bars >= max_hold_bars:
                exit_reason = "TIME"
                exit_price = bar_close

            if exit_reason:
                if pos_side == "LONG":
                    pnl_pct = (exit_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - exit_price) / pos_entry

                # 수수료 차감 (진입+청산 taker fee)
                pnl_pct -= fee_rate * 2
                pnl_pct *= leverage
                capital *= (1 + pnl_pct * risk_pct / (risk_pct if risk_pct > 0 else 1))
                # 실제: risk_pct 기반 사이징
                actual_pnl = pnl_pct * (risk_pct * capital / leverage) if leverage > 0 else 0
                capital = max(capital, 0)  # 파산 방지

                trades.append(ConfluenceTrade(
                    entry_date=pos_entry_date,
                    exit_date=bar_date,
                    side=pos_side,
                    entry_price=pos_entry,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_pct=round(pnl_pct * 100, 2),
                    confluence_score=pos_score,
                    funding_point=pos_funding,
                    mtf_point=pos_mtf,
                    vp_point=pos_vp,
                    market_regime=pos_regime,
                ))
                in_position = False

        # --- 신규 진입 판단 ---
        if not in_position and i >= start_idx + 1:
            # 슬라이스 프레임 (현재 봉까지)
            slice_frames: dict[str, pd.DataFrame] = {}
            bar_ts = entry_df.index[i]
            for tf_key, tf_df in frames.items():
                sliced = tf_df[tf_df.index <= bar_ts]
                if len(sliced) >= 50:
                    slice_frames[tf_key] = sliced

            if not slice_frames or entry_tf not in slice_frames:
                equity.append(capital)
                continue

            ctx = build_context(slice_frames[entry_tf])
            trend = ctx["structure"].get("trend", "RANGING")

            if trend == "BULLISH":
                side_str = "LONG"
            elif trend == "BEARISH":
                side_str = "SHORT"
            else:
                equity.append(capital)
                continue

            # MTF
            mtf_result = calc_mtf_confluence(slice_frames, side_str)
            mtf_score = mtf_result["score"]

            # VPVR
            vpvr = ctx["volume"].get("vpvr", {})
            adx_val = ctx["adx"].get("adx", 0)

            # 펀딩비 — 실제 데이터에서 가장 가까운 8h 구간 매칭
            bar_ts_ms = int(entry_df.index[i].timestamp() * 1000)
            fr = _lookup_funding(funding_ts_arr, funding_rate_arr, bar_ts_ms)

            # UTC 시간 (bar timestamp)
            hour_utc = entry_df.index[i].hour if hasattr(entry_df.index[i], "hour") else 12

            confluence = calc_confluence_score(
                funding_rate=fr,
                mtf_score=mtf_score,
                vpvr=vpvr,
                side=side_str,
                adx_val=adx_val,
                current_hour_utc=hour_utc,
            )

            score = confluence["total_score"]
            score_dist[score] = score_dist.get(score, 0) + 1

            if confluence["execute"] and score >= min_score:
                # ATR 기반 SL/TP
                close_arr = slice_frames[entry_tf]["close"].values.astype(np.float64)
                high_arr = slice_frames[entry_tf]["high"].values.astype(np.float64)
                low_arr = slice_frames[entry_tf]["low"].values.astype(np.float64)

                atr_arr = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
                atr_val = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) else bar_close * 0.02

                sl_dist = atr_val * atr_sl_mult
                direction = 1 if side_str == "LONG" else -1

                pos_entry = bar_close
                pos_sl = bar_close - direction * sl_dist
                pos_tps = [bar_close + direction * sl_dist * r for r in tp_ratios]
                pos_side = side_str
                pos_entry_date = bar_date
                pos_bars = 0
                pos_score = score
                pos_funding = confluence["funding_point"]
                pos_mtf = confluence["mtf_point"]
                pos_vp = confluence["vp_point"]
                # D1 트렌드로 시장 레짐 판단
                if "1d" in slice_frames and len(slice_frames["1d"]) >= 50:
                    d1_ctx = build_context(slice_frames["1d"])
                    d1_trend = d1_ctx["structure"].get("trend", "RANGING")
                    pos_regime = {"BULLISH": "BULL", "BEARISH": "BEAR"}.get(d1_trend, "RANGE")
                else:
                    pos_regime = "RANGE"
                in_position = True

        equity.append(capital)

    # --- 미청산 포지션 정리 ---
    if in_position:
        last_close = float(entry_df["close"].iloc[-1])
        if pos_side == "LONG":
            pnl_pct = (last_close - pos_entry) / pos_entry
        else:
            pnl_pct = (pos_entry - last_close) / pos_entry
        pnl_pct -= fee_rate * 2
        pnl_pct *= leverage
        trades.append(ConfluenceTrade(
            entry_date=pos_entry_date,
            exit_date=str(entry_df.index[-1])[:19],
            side=pos_side,
            entry_price=pos_entry,
            exit_price=last_close,
            exit_reason="END",
            pnl_pct=round(pnl_pct * 100, 2),
            confluence_score=pos_score,
            funding_point=pos_funding,
            mtf_point=pos_mtf,
            vp_point=pos_vp,
            market_regime=pos_regime,
        ))

    # --- 메트릭 계산 ---
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
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

    # Sharpe
    if len(eq_series) >= 2:
        rets = eq_series.pct_change().dropna()
        if rets.std() > 0:
            bars_per_year = 365 * 24 / _tf_to_hours(entry_tf)
            sharpe = float(rets.mean() / rets.std() * math.sqrt(bars_per_year))
        else:
            sharpe = None
    else:
        sharpe = None

    avg_score = sum(t.confluence_score for t in trades) / len(trades) if trades else 0.0

    return ConfluenceBacktestResult(
        symbol=symbol,
        timeframe=entry_tf,
        start_date=start,
        end_date=end,
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
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


def _build_funding_index(funding_map: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    """펀딩비 맵을 정렬된 배열로 변환 (bisect용)."""
    if not funding_map:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    sorted_items = sorted(funding_map.items())
    ts_arr = np.array([t for t, _ in sorted_items], dtype=np.int64)
    rate_arr = np.array([r for _, r in sorted_items], dtype=np.float64)
    return ts_arr, rate_arr


def _lookup_funding(ts_arr: np.ndarray, rate_arr: np.ndarray, bar_ts_ms: int) -> float:
    """이진탐색으로 가장 가까운 과거 펀딩비 조회 (O(log n))."""
    if len(ts_arr) == 0:
        return 0.0
    idx = int(np.searchsorted(ts_arr, bar_ts_ms, side="right")) - 1
    if idx < 0:
        return 0.0
    diff = bar_ts_ms - int(ts_arr[idx])
    if diff <= 28800000:  # 8h 이내
        return float(rate_arr[idx])
    return 0.0


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
    mapping = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "30m": 0.5, "1h": 1, "4h": 4, "1d": 24}
    return mapping.get(tf, 4)

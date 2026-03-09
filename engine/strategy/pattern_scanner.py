"""실시간 패턴 스캐너 — pred_multi + 패턴 감지 → TradingSignal 생성.

매 1H 봉 마감 시 호출:
  1. OHLCV 데이터 로드 (최근 300봉)
  2. pred_multi로 방향 예측
  3. 해당 방향 패턴만 스캔
  4. 리스크 관리 필터 적용
  5. TradingSignal 생성 → TradingOrchestrator로 전달
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.backtest.direction_predictor import predict_multi
from engine.data.base import get_provider
from engine.domain.trading.models import SignalAction, TradeSide, TradingSignal
from engine.strategy.pattern_detector import (
    PatternSignal,
    find_local_extrema,
    scan_patterns,
)
from engine.strategy.risk_manager import RiskManager, RiskConfig
from engine.strategy.watermelon_filter import apply_watermelon_boost, is_watermelon_active

logger = logging.getLogger(__name__)


@dataclass
class ScannerConfig:
    symbols: list[str]
    exchange: str = "binance"
    timeframe: str = "1h"
    lookback_bars: int = 300
    leverage: int = 3
    fee_rate: float = 0.0004
    slippage_pct: float = 0.01  # 슬리피지 (% 단위, 편도)
    use_watermelon: bool = True  # 수박지표 보조 신호 사용


@dataclass
class ScanResult:
    symbol: str
    direction: str
    signals: list[PatternSignal]
    trading_signals: list[TradingSignal]


def _fetch_ohlcv(symbol: str, exchange: str, timeframe: str,
                 lookback_bars: int) -> pd.DataFrame | None:
    """최근 N봉 OHLCV 로드."""
    try:
        provider = get_provider("crypto_spot", exchange=exchange)
        end = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        delta = pd.Timedelta(hours=1) if timeframe == "1h" else pd.Timedelta(minutes=30)
        start = (pd.Timestamp.now(tz="UTC") - delta * lookback_bars).strftime("%Y-%m-%d")
        df = provider.fetch_ohlcv(symbol, start, end, timeframe)
        if df.empty or len(df) < 100:
            logger.warning("%s 데이터 부족: %d봉", symbol, len(df))
            return None
        return df
    except Exception as e:
        logger.error("%s 데이터 로드 실패: %s", symbol, e)
        return None


def _apply_slippage(signal: PatternSignal, slippage_pct: float) -> PatternSignal:
    """슬리피지 적용: 진입가 불리하게, SL/TP 조정."""
    slip = signal.entry_price * slippage_pct / 100

    if signal.side == "LONG":
        signal.entry_price += slip
        signal.take_profit += slip
    else:
        signal.entry_price -= slip
        signal.take_profit -= slip

    return signal


def _to_trading_signal(
    pattern_sig: PatternSignal,
    symbol: str,
    timeframe: str,
    direction: str,
) -> TradingSignal:
    """PatternSignal → TradingSignal 변환."""
    side = TradeSide.long if pattern_sig.side == "LONG" else TradeSide.short
    return TradingSignal(
        strategy_id=f"pattern_{pattern_sig.pattern.lower()}",
        symbol=symbol,
        timeframe=timeframe,
        action=SignalAction.entry,
        side=side,
        entry_price=pattern_sig.entry_price,
        stop_loss=pattern_sig.stop_loss,
        take_profits=[pattern_sig.take_profit],
        confidence=0.0,
        reason=f"{pattern_sig.pattern} 패턴 감지 (방향: {direction})",
        metadata={
            "pattern": pattern_sig.pattern,
            "direction": direction,
            **{k: str(v) for k, v in pattern_sig.metadata.items()},
        },
    )


def scan_symbol(
    symbol: str,
    config: ScannerConfig,
    risk_manager: RiskManager | None = None,
) -> ScanResult:
    """단일 심볼 스캔: 방향 예측 → 패턴 감지 → 신호 생성."""
    df = _fetch_ohlcv(symbol, config.exchange, config.timeframe, config.lookback_bars)
    if df is None:
        return ScanResult(symbol=symbol, direction="NEUTRAL", signals=[], trading_signals=[])

    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)

    i = len(close) - 1  # 현재 (마지막) 봉

    # EMA 계산
    ema_fast = pd.Series(close).ewm(span=21, adjust=False).mean().values
    ema_slow = pd.Series(close).ewm(span=55, adjust=False).mean().values

    # 방향 예측
    direction = predict_multi(close, high, low, i, ema_fast, ema_slow)

    # 극값 계산
    low_mins, low_maxs = find_local_extrema(low, order=5)
    high_mins, high_maxs = find_local_extrema(high, order=5)

    # 패턴 스캔
    pattern_signals = scan_patterns(
        close, high, low, i, direction,
        low_mins, low_maxs, high_mins, high_maxs,
    )

    # 슬리피지 적용
    pattern_signals = [_apply_slippage(s, config.slippage_pct) for s in pattern_signals]

    # 리스크 관리 필터
    if risk_manager:
        pattern_signals = [s for s in pattern_signals if risk_manager.allow_entry(symbol, s)]

    # 수박지표 보조 확신도 부스트 (LONG 신호만)
    watermelon_active = False
    if config.use_watermelon and direction == "LONG":
        try:
            provider = get_provider("crypto_spot", exchange=config.exchange)
            end_str = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
            start_1d = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=600)).strftime("%Y-%m-%d")
            df_1d = provider.fetch_ohlcv(symbol, start_1d, end_str, "1d")
            watermelon_active = is_watermelon_active(df_1d)
        except Exception as e:
            logger.warning("%s 수박지표 로드 실패: %s", symbol, e)

    # TradingSignal 변환
    trading_signals = []
    for s in pattern_signals:
        ts = _to_trading_signal(s, symbol, config.timeframe, direction)
        if watermelon_active and s.side == "LONG":
            ts.confidence = apply_watermelon_boost(ts.confidence, True)
            ts.metadata["watermelon"] = "active"
        trading_signals.append(ts)

    return ScanResult(
        symbol=symbol,
        direction=direction,
        signals=pattern_signals,
        trading_signals=trading_signals,
    )


def scan_all(
    config: ScannerConfig,
    risk_manager: RiskManager | None = None,
) -> list[ScanResult]:
    """전체 심볼 스캔."""
    results = []
    for symbol in config.symbols:
        result = scan_symbol(symbol, config, risk_manager)
        results.append(result)
        if result.trading_signals:
            for ts in result.trading_signals:
                logger.info(
                    "[%s] %s %s @ %.2f (SL: %.2f, TP: %s)",
                    symbol, ts.side.value.upper(), ts.reason,
                    ts.entry_price,
                    ts.stop_loss,
                    [f"{tp:.2f}" for tp in ts.take_profits],
                )
    return results

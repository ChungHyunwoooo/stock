from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import talib

from engine.analysis import build_context
from engine.analysis.confluence import calc_confluence_score
from engine.analysis.mtf_confluence import calc_mtf_confluence
from engine.strategy.funding import fetch_funding_rates_batch
from engine.patterns.chart_patterns import detect_chart_patterns
from engine.analysis.direction import calc_confidence_v2, get_last_breakdown
from engine.application.trading.orchestrator import TradingOrchestrator
from engine.application.trading.reports import AnalysisReport
from engine.application.trading.strategies import DefinitionSignalGenerator, StrategyCatalog
from engine.data.provider_base import get_provider
from engine.core.models import SignalAction, TradeSide, TradingSignal
from engine.schema import StrategyDefinition

logger = logging.getLogger(__name__)

_CONFIG_DEFAULT_PATH = Path("config/alert_runtime.json")
_STATE_DEFAULT_PATH = Path("state/alert_scan_state.json")
_TIMEFRAME_DELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

@dataclass(slots=True)
class FuturesConfluenceConfig:
    enabled: bool = False
    min_score: int = 2
    funding_threshold_long: float = -0.0005
    funding_threshold_short: float = 0.001
    mtf_min_score: float = 0.6
    risk_per_trade_pct: float = 1.0
    leverage: int = 3
    tp_ratios: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.5])
    tp_portions: list[float] = field(default_factory=lambda: [0.5, 0.3, 0.2])

@dataclass(slots=True)
class AlertRuntimeConfig:
    enabled: bool = False
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframes: list[str] = field(default_factory=lambda: ["5m", "15m", "30m", "1h"])
    strategy_dir: str = "strategies"
    scan_interval_sec: int = 60
    cooldown_sec: int = 900
    quantity: float = 1.0
    lookback_bars: int = 300
    futures_confluence: FuturesConfluenceConfig = field(default_factory=FuturesConfluenceConfig)

    @classmethod
    def load(cls, path: str | Path = _CONFIG_DEFAULT_PATH) -> AlertRuntimeConfig:
        config_path = Path(path)
        if not config_path.exists():
            return cls()
        data = json.loads(config_path.read_text())
        fc_data = data.pop("futures_confluence", {})
        config = cls(**data)
        if fc_data:
            config.futures_confluence = FuturesConfluenceConfig(**fc_data)
        return config

class RecentSignalAnalysisService:
    def __init__(
        self,
        strategy_dir: str = "strategies",
        signal_generator: DefinitionSignalGenerator | None = None,
    ) -> None:
        self.catalog = StrategyCatalog(strategy_dir)
        self.signal_generator = signal_generator or DefinitionSignalGenerator()

    def analyze_recent(
        self,
        symbol: str,
        timeframe: str,
        lookback_bars: int = 300,
        exchange: str | None = None,
    ) -> list[TradingSignal]:
        report = self.build_report(symbol=symbol, timeframe=timeframe, lookback_bars=lookback_bars, exchange=exchange)
        return report.signals

    def build_report(
        self,
        symbol: str,
        timeframe: str,
        lookback_bars: int = 300,
        exchange: str | None = None,
    ) -> AnalysisReport:
        definitions = self.catalog.list_definitions()
        now = pd.Timestamp.utcnow()
        delta = _TIMEFRAME_DELTA.get(timeframe, pd.Timedelta(minutes=5))
        start = (now - delta * lookback_bars).strftime("%Y-%m-%d %H:%M:%S")
        end = now.strftime("%Y-%m-%d %H:%M:%S")

        selected_exchange = exchange or _exchange_for_symbol(symbol)
        market = _market_for_symbol(symbol)
        provider = get_provider(market, exchange=selected_exchange)
        frame = provider.fetch_ohlcv(symbol, start, end, timeframe)
        if frame.empty:
            return AnalysisReport(
                symbol=symbol,
                exchange=selected_exchange,
                timeframe=timeframe,
                scanned_at=now.isoformat(),
                last_price=0.0,
                price_change_pct=0.0,
                range_pct=0.0,
                volume_ratio=0.0,
                trend_bias="NO_DATA",
                bars=0,
                high=0.0,
                low=0.0,
                signal_count=0,
                notes=["No OHLCV data returned."],
                signals=[],
            )

        signals: list[TradingSignal] = []
        for strategy in definitions:
            selected_market = _select_market_for_symbol(strategy, symbol)
            if selected_market is None or selected_market != market:
                continue
            signal = self.signal_generator.generate(strategy, frame.copy(), symbol)
            if signal is None:
                continue
            signal.timeframe = timeframe
            signal.metadata.update(
                {
                    "exchange": selected_exchange,
                    "scanned_at": now.isoformat(),
                    "strategy_file_timeframes": ",".join(strategy.timeframes),
                }
            )
            signals.append(signal)

        # 차트 패턴 기반 시그널 생성
        patterns = detect_chart_patterns(frame, lookback=min(len(frame), 120))
        for pattern in patterns:
            if pattern.confidence < 0.6:
                continue

            if pattern.direction == "NEUTRAL":
                continue
            side = TradeSide.long if pattern.direction == "BULLISH" else TradeSide.short

            ctx = build_context(frame)
            side_str = side.value.upper()

            # 역추세 체크
            trend = ctx["structure"].get("trend", "RANGING")
            adx_val = ctx["adx"].get("adx", 0)
            is_counter = (
                (side_str == "LONG" and trend == "BEARISH")
                or (side_str == "SHORT" and trend == "BULLISH")
            )
            if is_counter and adx_val > 30:
                continue

            confidence = calc_confidence_v2(
                base=pattern.confidence,
                adx=ctx["adx"],
                volume=ctx["volume"],
                structure=ctx["structure"],
                candle=ctx["candle"],
                key_levels=ctx["key_levels"],
                side=side_str,
            )
            breakdown = get_last_breakdown()

            if is_counter:
                confidence *= 0.3

            last_price = float(frame["close"].iloc[-1])
            # 패턴 key_prices에서 SL 산출
            if side == TradeSide.long:
                sl_price = pattern.key_prices.get("neckline", pattern.key_prices.get("cup_bottom", last_price * 0.97))
                risk = abs(last_price - sl_price)
                take_profits = [last_price + risk * r for r in [1.5, 2.5, 3.5]]
            else:
                sl_price = pattern.key_prices.get("neckline", pattern.key_prices.get("peak1", last_price * 1.03))
                risk = abs(sl_price - last_price)
                take_profits = [last_price - risk * r for r in [1.5, 2.5, 3.5]]

            pattern_signal = TradingSignal(
                strategy_id=f"PATTERN:{pattern.name}",
                symbol=symbol,
                timeframe=timeframe,
                action=SignalAction.entry,
                side=side,
                entry_price=last_price,
                stop_loss=sl_price,
                take_profits=take_profits,
                confidence=confidence,
                reason=pattern.description,
                metadata={
                    "strategy_name": f"Chart Pattern: {pattern.name}",
                    "status": "active",
                    "confidence_breakdown": breakdown,
                    "trend": trend,
                    "adx": adx_val,
                    "vol_ratio": ctx["volume"].get("vol_ratio", 0),
                    "obv_trend": ctx["volume"].get("obv_trend", ""),
                    "counter_trend": is_counter,
                    "is_climactic": ctx["volume"].get("is_climactic", False),
                    "at_support": ctx["key_levels"].get("at_support", False),
                    "at_resistance": ctx["key_levels"].get("at_resistance", False),
                    "exchange": selected_exchange,
                    "timeframe": timeframe,
                },
            )
            signals.append(pattern_signal)

        signals.sort(key=lambda item: (item.confidence, item.strategy_id), reverse=True)
        return _build_report_from_frame(
            frame=frame,
            symbol=symbol,
            exchange=selected_exchange,
            timeframe=timeframe,
            scanned_at=now.isoformat(),
            signals=signals,
        )

    def generate_confluence_signals(
        self,
        symbol: str,
        frames: dict[str, pd.DataFrame],
        funding_rate: float | None,
        config: FuturesConfluenceConfig,
    ) -> list[TradingSignal]:
        """Confluence 점수 기반 선물 시그널 생성."""
        if not frames:
            return []

        # 가장 긴 TF의 frame으로 build_context 호출
        tf_order = ["1d", "4h", "1h", "30m", "15m", "5m"]
        longest_tf = None
        longest_frame: pd.DataFrame | None = None
        for tf in tf_order:
            if tf in frames and not frames[tf].empty:
                longest_tf = tf
                longest_frame = frames[tf]
                break

        if longest_frame is None or longest_tf is None:
            return []

        ctx = build_context(longest_frame)

        # side 결정: trend BULLISH→LONG, BEARISH→SHORT, RANGING→스킵
        trend = ctx["structure"].get("trend", "RANGING")
        if trend == "BULLISH":
            side_str = "LONG"
            side = TradeSide.long
        elif trend == "BEARISH":
            side_str = "SHORT"
            side = TradeSide.short
        else:
            return []

        # MTF confluence 계산
        mtf_result = calc_mtf_confluence(frames, side_str)
        mtf_score = mtf_result["score"]

        # VPVR: build_context의 volume에서 vpvr 가져옴
        vpvr = ctx["volume"].get("vpvr", {})

        # ADX
        adx_val = ctx["adx"].get("adx", 0.0)

        # confluence score 계산
        confluence = calc_confluence_score(
            funding_rate=funding_rate,
            mtf_score=mtf_score,
            vpvr=vpvr,
            side=side_str,
            adx_val=adx_val,
        )

        if not confluence["execute"]:
            return []

        score = confluence["total_score"]
        logger.info("Confluence signal: %s %s score=%d", symbol, side_str, score)

        # 가장 짧은 TF의 frame에서 entry price와 ATR 계산
        entry_frame = longest_frame
        entry_tf = longest_tf
        for tf in reversed(tf_order):
            if tf in frames and not frames[tf].empty:
                entry_frame = frames[tf]
                entry_tf = tf
                break

        last_price = float(entry_frame["close"].iloc[-1])

        # ATR 기반 SL/TP 계산
        high = entry_frame["high"].values.astype(np.float64)
        low = entry_frame["low"].values.astype(np.float64)
        close = entry_frame["close"].values.astype(np.float64)
        atr_arr = talib.ATR(high, low, close, timeperiod=14)
        atr_val = float(atr_arr[-1]) if len(atr_arr) > 0 and not np.isnan(atr_arr[-1]) else last_price * 0.02

        sl_distance = atr_val * 1.5
        if side == TradeSide.long:
            sl_price = last_price - sl_distance
            take_profits = [last_price + sl_distance * r for r in config.tp_ratios]
        else:
            sl_price = last_price + sl_distance
            take_profits = [last_price - sl_distance * r for r in config.tp_ratios]

        signal = TradingSignal(
            strategy_id="CONFLUENCE:FUTURES",
            symbol=symbol,
            timeframe=entry_tf,
            action=SignalAction.entry,
            side=side,
            entry_price=last_price,
            stop_loss=sl_price,
            take_profits=take_profits,
            confidence=score / 3.0,
            reason=confluence["details"],
            metadata={
                "strategy_name": "Futures Confluence",
                "confluence_score": score,
                "funding_rate": funding_rate if funding_rate is not None else 0.0,
                "mtf_score": mtf_score,
                "trend": trend,
                "adx": adx_val,
                "leverage": config.leverage,
                "risk_pct": config.risk_per_trade_pct,
                "regime_ok": confluence["regime_ok"],
                "session": confluence["session"],
                "session_ok": confluence["session_ok"],
            },
        )
        return [signal]

class CooldownStore:
    def __init__(self, path: str | Path = _STATE_DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        return {k: float(v) for k, v in json.loads(self.path.read_text()).items()}

    def save(self, data: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

class AlertScannerRuntime:
    def __init__(
        self,
        orchestrator: TradingOrchestrator,
        config: AlertRuntimeConfig | None = None,
        cooldown_store: CooldownStore | None = None,
        analysis_service: RecentSignalAnalysisService | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or AlertRuntimeConfig.load()
        self.cooldown_store = cooldown_store or CooldownStore()
        self.analysis_service = analysis_service or RecentSignalAnalysisService(
            strategy_dir=self.config.strategy_dir
        )
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def scan_once(self) -> list[TradingSignal]:
        sent_state = self.cooldown_store.load()
        emitted: list[TradingSignal] = []
        now = time.time()

        for symbol in self.config.symbols:
            for timeframe in self.config.timeframes:
                signals = self.analysis_service.analyze_recent(
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_bars=self.config.lookback_bars,
                )
                for signal in signals:
                    key = f"{signal.strategy_id}:{signal.symbol}:{signal.timeframe}:{signal.action.value}"
                    if now - sent_state.get(key, 0.0) < self.config.cooldown_sec:
                        continue
                    self.orchestrator.process_signal(signal, quantity=self.config.quantity)
                    sent_state[key] = now
                    emitted.append(signal)

        # --- Confluence 점수 기반 선물 신호 파이프라인 ---
        fc_config = self.config.futures_confluence
        if fc_config.enabled:
            try:
                funding_rates = fetch_funding_rates_batch(self.config.symbols)
            except Exception:
                logger.exception("Failed to fetch funding rates")
                funding_rates = {}

            # 이미 fetch된 frame 캐시 (symbol+tf → DataFrame)
            frame_cache: dict[str, pd.DataFrame] = {}

            for symbol in self.config.symbols:
                # 여러 TF의 frame을 dict로 수집
                symbol_frames: dict[str, pd.DataFrame] = {}
                for timeframe in self.config.timeframes:
                    cache_key = f"{symbol}:{timeframe}"
                    if cache_key not in frame_cache:
                        try:
                            delta = _TIMEFRAME_DELTA.get(timeframe, pd.Timedelta(minutes=5))
                            tf_now = pd.Timestamp.utcnow()
                            start = (tf_now - delta * self.config.lookback_bars).strftime("%Y-%m-%d %H:%M:%S")
                            end = tf_now.strftime("%Y-%m-%d %H:%M:%S")
                            exchange = _exchange_for_symbol(symbol)
                            market = _market_for_symbol(symbol)
                            provider = get_provider(market, exchange=exchange)
                            frame = provider.fetch_ohlcv(symbol, start, end, timeframe)
                            frame_cache[cache_key] = frame
                        except Exception:
                            logger.exception("Failed to fetch OHLCV for %s %s", symbol, timeframe)
                            frame_cache[cache_key] = pd.DataFrame()
                    frame = frame_cache[cache_key]
                    if not frame.empty:
                        symbol_frames[timeframe] = frame

                if not symbol_frames:
                    continue

                funding_rate = funding_rates.get(symbol)
                confluence_signals = self.analysis_service.generate_confluence_signals(
                    symbol=symbol,
                    frames=symbol_frames,
                    funding_rate=funding_rate,
                    config=fc_config,
                )

                for signal in confluence_signals:
                    key = f"{signal.strategy_id}:{signal.symbol}:{signal.timeframe}:{signal.action.value}"
                    if now - sent_state.get(key, 0.0) < self.config.cooldown_sec:
                        continue
                    self.orchestrator.process_signal(signal, quantity=self.config.quantity)
                    sent_state[key] = now
                    emitted.append(signal)

        self.cooldown_store.save(sent_state)
        return emitted

    def start_background(self) -> bool:
        if not self.config.enabled:
            return False
        if self._thread and self._thread.is_alive():
            return True

        def _run() -> None:
            while not self._stop_event.is_set():
                try:
                    self.scan_once()
                except Exception:
                    logger.exception("Alert scanner cycle failed")
                self._stop_event.wait(self.config.scan_interval_sec)

        self._stop_event.clear()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        self._stop_event.set()
        return True

def _build_report_from_frame(
    frame: pd.DataFrame,
    symbol: str,
    exchange: str,
    timeframe: str,
    scanned_at: str,
    signals: list[TradingSignal],
) -> AnalysisReport:
    last = frame.iloc[-1]
    first_close = float(frame["close"].iloc[0]) if len(frame) else 0.0
    last_price = float(last["close"])
    high = float(frame["high"].max())
    low = float(frame["low"].min())
    volume_mean = float(frame["volume"].tail(min(20, len(frame))).mean()) if len(frame) else 0.0
    volume_ratio = float(last["volume"]) / volume_mean if volume_mean else 0.0
    change_pct = ((last_price - first_close) / first_close * 100) if first_close else 0.0
    range_pct = ((high - low) / low * 100) if low else 0.0
    ema_fast = frame["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema_slow = frame["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    if last_price > ema_fast > ema_slow:
        trend_bias = "BULLISH"
    elif last_price < ema_fast < ema_slow:
        trend_bias = "BEARISH"
    else:
        trend_bias = "RANGE"

    notes = [
        f"{len(signals)} live signal(s) found" if signals else "No live entry/exit signal now",
        f"Volume ratio {volume_ratio:.2f}x against recent average",
        f"Trend bias inferred as {trend_bias}",
    ]
    return AnalysisReport(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        scanned_at=scanned_at,
        last_price=last_price,
        price_change_pct=change_pct,
        range_pct=range_pct,
        volume_ratio=volume_ratio,
        trend_bias=trend_bias,
        bars=len(frame),
        high=high,
        low=low,
        signal_count=len(signals),
        notes=notes,
        signals=signals,
    )

def _strategy_supports_symbol(strategy: StrategyDefinition, symbol: str) -> bool:
    return _select_market_for_symbol(strategy, symbol) is not None

def _select_market_for_symbol(strategy: StrategyDefinition, symbol: str):
    normalized = symbol.upper()
    is_crypto = "/" in normalized or normalized.startswith(("KRW-", "BTC-", "USDT-"))
    is_kr_stock = normalized.isdigit()

    for market in strategy.markets:
        if market.value in {"crypto_spot", "crypto_futures"} and is_crypto:
            return market
        if market.value == "kr_stock" and is_kr_stock:
            return market
        if market.value == "us_stock" and not is_crypto and not is_kr_stock:
            return market

    return None

def _exchange_for_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.startswith("KRW-"):
        return "upbit"
    return "binance"

def _market_for_symbol(symbol: str):
    normalized = symbol.upper()
    if "/" in normalized or normalized.startswith(("KRW-", "BTC-", "USDT-")):
        from engine.schema import MarketType

        return MarketType.crypto_spot
    from engine.schema import MarketType

    if normalized.isdigit():
        return MarketType.kr_stock
    return MarketType.us_stock

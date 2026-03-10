
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from engine.analysis import build_context
from engine.analysis.direction import calc_confidence_v2, get_last_breakdown
from engine.core.models import SignalAction, TradeSide, TradingSignal
from engine.schema import Direction, StrategyDefinition
from engine.strategy.strategy_evaluator import StrategyEngine

class StrategyCatalog:
    def __init__(self, base_dir: str | Path = "strategies") -> None:
        self.base_dir = Path(base_dir)

    def list_definitions(self) -> list[StrategyDefinition]:
        definitions: list[StrategyDefinition] = []
        registry_path = self.base_dir / "registry.json"
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
            for entry in registry.get("strategies", []):
                if entry.get("status") != "active":
                    continue
                def_path = Path(entry.get("definition", ""))
                if def_path.exists():
                    definitions.append(StrategyDefinition.model_validate(json.loads(def_path.read_text())))
        return definitions

class DefinitionSignalGenerator:
    def __init__(self, engine: StrategyEngine | None = None) -> None:
        self.engine = engine or StrategyEngine()

    def generate(self, strategy: StrategyDefinition, df: pd.DataFrame, symbol: str) -> TradingSignal | None:
        if df.empty:
            return None

        enriched = self.engine.generate_signals(strategy, df)
        last = enriched.iloc[-1]
        signal_value = int(last.get("signal", 0))
        if signal_value == 0:
            return None

        action = SignalAction.entry if signal_value > 0 else SignalAction.exit
        entry_price = float(last["close"])

        # analysis context 1회 계산
        ctx = build_context(df)

        # direction 결정: both인 경우 시장 구조로 판단
        if strategy.direction is Direction.short:
            side = TradeSide.short
        elif strategy.direction is Direction.both:
            trend = ctx["structure"].get("trend", "RANGING")
            side = TradeSide.short if trend == "BEARISH" else TradeSide.long
        else:
            side = TradeSide.long

        # exit 시그널에는 SL/TP 불필요, 시장 컨텍스트만 첨부
        if action == SignalAction.exit:
            return TradingSignal(
                strategy_id=f"{strategy.name}:{strategy.version}",
                symbol=symbol,
                timeframe=strategy.timeframes[0] if strategy.timeframes else "1d",
                action=action,
                side=side,
                entry_price=entry_price,
                stop_loss=None,
                take_profits=[],
                confidence=0.0,
                reason=strategy.description or strategy.name,
                metadata={
                    "strategy_name": strategy.name,
                    "status": strategy.status.value,
                    "trend": ctx["structure"].get("trend", ""),
                    "adx": ctx["adx"].get("adx", 0),
                    "vol_ratio": ctx["volume"].get("vol_ratio", 0),
                    "obv_trend": ctx["volume"].get("obv_trend", ""),
                },
            )

        stop_loss = self._value_or_none(last.get("stop_loss_price"))
        take_profit = self._value_or_none(last.get("take_profit_price"))

        if take_profit is not None:
            take_profits = [take_profit]
        elif stop_loss is not None and stop_loss != entry_price:
            risk = abs(entry_price - stop_loss)
            direction = 1 if side == TradeSide.long else -1
            take_profits = [
                entry_price + direction * risk * 1.5,
                entry_price + direction * risk * 2.5,
                entry_price + direction * risk * 3.5,
            ]
        else:
            take_profits = []

        side_str = side.value.upper()
        confidence = calc_confidence_v2(
            base=0.6,
            adx=ctx["adx"],
            volume=ctx["volume"],
            structure=ctx["structure"],
            candle=ctx["candle"],
            key_levels=ctx["key_levels"],
            side=side_str,
        )
        breakdown = get_last_breakdown()

        # 역추세 필터
        is_counter_trend = (
            (side_str == "LONG" and ctx["structure"].get("trend") == "BEARISH")
            or (side_str == "SHORT" and ctx["structure"].get("trend") == "BULLISH")
        )
        adx_val = ctx["adx"].get("adx", 0)

        # 강한 역추세: 시그널 차단
        if is_counter_trend and adx_val > 30:
            return None

        # 약한 역추세: confidence 감점
        if is_counter_trend:
            confidence *= 0.3

        metadata = {
            "strategy_name": strategy.name,
            "status": strategy.status.value,
            "confidence_breakdown": breakdown,
            "trend": ctx["structure"].get("trend", ""),
            "adx": ctx["adx"].get("adx", 0),
            "vol_ratio": ctx["volume"].get("vol_ratio", 0),
            "obv_trend": ctx["volume"].get("obv_trend", ""),
            "counter_trend": (
                (side_str == "LONG" and ctx["structure"].get("trend") == "BEARISH")
                or (side_str == "SHORT" and ctx["structure"].get("trend") == "BULLISH")
            ),
            "is_climactic": ctx["volume"].get("is_climactic", False),
            "at_support": ctx["key_levels"].get("at_support", False),
            "at_resistance": ctx["key_levels"].get("at_resistance", False),
        }

        return TradingSignal(
            strategy_id=f"{strategy.name}:{strategy.version}",
            symbol=symbol,
            timeframe=strategy.timeframes[0] if strategy.timeframes else "1d",
            action=action,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profits=take_profits,
            confidence=confidence,
            reason=strategy.description or strategy.name,
            metadata=metadata,
        )

    @staticmethod
    def _value_or_none(value: object) -> float | None:
        if value is None or pd.isna(value):
            return None
        return float(value)

"""Position tracker with SL/TP/Trailing Stop monitoring."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from engine.alerts.discord import Signal

logger = logging.getLogger(__name__)

from engine.config_path import config_file

CONFIG_PATH = config_file("positions.json")


@dataclass
class Alert:
    type: str  # TP1, TP2, SL, TS, OPEN, CLOSE
    position: Position
    message: str


@dataclass
class Position:
    id: str
    signal: Signal
    status: str  # OPEN / CLOSED_SL / CLOSED_TP / CLOSED_TS / MANUAL
    entry_price: float
    current_price: float
    stop_loss: float
    take_profits: list[float]
    trailing_stop: float | None = None
    trailing_pct: float = 0.015
    highest_since_entry: float = 0.0
    lowest_since_entry: float = 0.0
    pnl_pct: float = 0.0
    opened_at: str = ""
    closed_at: str | None = None
    tp1_hit: bool = False
    tp2_hit: bool = False

    def __post_init__(self) -> None:
        if not self.opened_at:
            self.opened_at = datetime.now(timezone.utc).isoformat()


class PositionTracker:
    def __init__(self) -> None:
        self.positions: list[Position] = []
        self._load()

    def open_position(self, signal: Signal, trailing_pct: float = 0.015) -> Position:
        entry = signal.entry
        if signal.side == "LONG":
            trailing_stop = entry * (1 - trailing_pct)
            highest_since_entry = entry
            lowest_since_entry = entry
        else:  # SHORT
            trailing_stop = entry * (1 + trailing_pct)
            highest_since_entry = entry
            lowest_since_entry = entry

        pos = Position(
            id=str(uuid.uuid4()),
            signal=signal,
            status="OPEN",
            entry_price=entry,
            current_price=entry,
            stop_loss=signal.stop_loss,
            take_profits=list(signal.take_profits),
            trailing_stop=trailing_stop,
            trailing_pct=trailing_pct,
            highest_since_entry=highest_since_entry,
            lowest_since_entry=lowest_since_entry,
        )
        self.positions.append(pos)
        self.save()
        logger.info("Opened position %s for %s %s @ %s", pos.id, signal.side, signal.symbol, entry)
        return pos

    def update_prices(self, prices: dict[str, float]) -> list[Alert]:
        alerts: list[Alert] = []
        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            if pos.signal.symbol not in prices:
                continue

            current = prices[pos.signal.symbol]
            pos.current_price = current

            if pos.signal.side == "LONG":
                pos.pnl_pct = (current - pos.entry_price) / pos.entry_price
                if current > pos.highest_since_entry:
                    pos.highest_since_entry = current
            else:
                pos.pnl_pct = (pos.entry_price - current) / pos.entry_price
                if current < pos.lowest_since_entry:
                    pos.lowest_since_entry = current

            sl_alert = self.check_stop_loss(pos)
            if sl_alert:
                alerts.append(sl_alert)
                continue

            tp_alert = self.check_take_profit(pos)
            if tp_alert:
                alerts.append(tp_alert)
                if pos.status != "OPEN":
                    continue

            ts_alert = self.update_trailing_stop(pos)
            if ts_alert:
                alerts.append(ts_alert)

        self.save()
        return alerts

    def check_stop_loss(self, pos: Position) -> Alert | None:
        triggered = False
        if pos.signal.side == "LONG" and pos.current_price <= pos.stop_loss:
            triggered = True
        elif pos.signal.side == "SHORT" and pos.current_price >= pos.stop_loss:
            triggered = True

        if triggered:
            pos.status = "CLOSED_SL"
            pos.closed_at = datetime.now(timezone.utc).isoformat()
            return Alert(type="SL", position=pos, message="손절 도달! 포지션 청산 권장")
        return None

    def check_take_profit(self, pos: Position) -> Alert | None:
        if not pos.take_profits:
            return None

        if not pos.tp1_hit:
            tp1 = pos.take_profits[0]
            hit = False
            if pos.signal.side == "LONG" and pos.current_price >= tp1:
                hit = True
            elif pos.signal.side == "SHORT" and pos.current_price <= tp1:
                hit = True

            if hit:
                pos.tp1_hit = True
                return Alert(type="TP1", position=pos, message="1차 익절 도달! 절반 청산 권장")

        elif len(pos.take_profits) > 1:
            tp2 = pos.take_profits[1]
            hit = False
            if pos.signal.side == "LONG" and pos.current_price >= tp2:
                hit = True
            elif pos.signal.side == "SHORT" and pos.current_price <= tp2:
                hit = True

            if hit:
                pos.tp2_hit = True
                pos.status = "CLOSED_TP"
                pos.closed_at = datetime.now(timezone.utc).isoformat()
                return Alert(type="TP2", position=pos, message="2차 익절 도달! 전량 청산 권장")

        return None

    def update_trailing_stop(self, pos: Position) -> Alert | None:
        if pos.trailing_stop is None:
            return None

        if pos.signal.side == "LONG":
            if pos.current_price > pos.highest_since_entry:
                pos.highest_since_entry = pos.current_price
                pos.trailing_stop = pos.highest_since_entry * (1 - pos.trailing_pct)
            if pos.current_price <= pos.trailing_stop:
                pos.status = "CLOSED_TS"
                pos.closed_at = datetime.now(timezone.utc).isoformat()
                return Alert(type="TS", position=pos, message="트레일링 스탑 발동! 이익 확보")
        else:  # SHORT
            if pos.current_price < pos.lowest_since_entry:
                pos.lowest_since_entry = pos.current_price
                pos.trailing_stop = pos.lowest_since_entry * (1 + pos.trailing_pct)
            if pos.current_price >= pos.trailing_stop:
                pos.status = "CLOSED_TS"
                pos.closed_at = datetime.now(timezone.utc).isoformat()
                return Alert(type="TS", position=pos, message="트레일링 스탑 발동! 이익 확보")

        return None

    def close_position(self, pos_id: str, reason: str = "MANUAL") -> Alert | None:
        for pos in self.positions:
            if pos.id == pos_id:
                pos.status = reason if reason != "MANUAL" else "MANUAL"
                pos.closed_at = datetime.now(timezone.utc).isoformat()
                self.save()
                return Alert(type="CLOSE", position=pos, message=f"포지션 수동 청산: {reason}")
        return None

    def get_open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "OPEN"]

    def get_history(self) -> list[Position]:
        return [p for p in self.positions if p.status != "OPEN"]

    def open_symbols(self) -> list[str]:
        return list({p.signal.symbol for p in self.positions if p.status == "OPEN"})

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = []
        for pos in self.positions:
            pos_dict = {
                "id": pos.id,
                "signal": asdict(pos.signal),
                "status": pos.status,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "stop_loss": pos.stop_loss,
                "take_profits": pos.take_profits,
                "trailing_stop": pos.trailing_stop,
                "trailing_pct": pos.trailing_pct,
                "highest_since_entry": pos.highest_since_entry,
                "lowest_since_entry": pos.lowest_since_entry,
                "pnl_pct": pos.pnl_pct,
                "opened_at": pos.opened_at,
                "closed_at": pos.closed_at,
                "tp1_hit": pos.tp1_hit,
                "tp2_hit": pos.tp2_hit,
            }
            data.append(pos_dict)
        CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text())
            for item in data:
                sig_data = item["signal"]
                signal = Signal(
                    strategy=sig_data["strategy"],
                    symbol=sig_data["symbol"],
                    side=sig_data["side"],
                    entry=sig_data["entry"],
                    stop_loss=sig_data["stop_loss"],
                    take_profits=sig_data.get("take_profits", []),
                    leverage=sig_data.get("leverage", 1),
                    timeframe=sig_data.get("timeframe", "1d"),
                    confidence=sig_data.get("confidence", 0.0),
                    reason=sig_data.get("reason", ""),
                    timestamp=sig_data.get("timestamp", ""),
                )
                pos = Position(
                    id=item["id"],
                    signal=signal,
                    status=item["status"],
                    entry_price=item["entry_price"],
                    current_price=item["current_price"],
                    stop_loss=item["stop_loss"],
                    take_profits=item["take_profits"],
                    trailing_stop=item.get("trailing_stop"),
                    trailing_pct=item.get("trailing_pct", 0.015),
                    highest_since_entry=item.get("highest_since_entry", 0.0),
                    lowest_since_entry=item.get("lowest_since_entry", 0.0),
                    pnl_pct=item.get("pnl_pct", 0.0),
                    opened_at=item.get("opened_at", ""),
                    closed_at=item.get("closed_at"),
                    tp1_hit=item.get("tp1_hit", False),
                    tp2_hit=item.get("tp2_hit", False),
                )
                self.positions.append(pos)
        except Exception as e:
            logger.error("Failed to load positions: %s", e)
            self.positions = []


from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.schema import StrategyDefinition
from engine.core.db_models import (
    BacktestRecord,
    KnowledgeRecord,
    OrderRecord,
    PaperBalance,
    PaperPnlSnapshot,
    StrategyRecord,
    TradeRecord,
)

class StrategyRepository:
    def save(self, session: Session, strategy: StrategyDefinition) -> StrategyRecord:
        record = StrategyRecord(
            name=strategy.name,
            version=strategy.version,
            status=strategy.status.value,
            definition_json=strategy.model_dump_json(),
        )
        session.add(record)
        session.flush()
        return record

    def get(self, session: Session, strategy_id: int) -> StrategyRecord | None:
        return session.get(StrategyRecord, strategy_id)

    def list_all(self, session: Session, status: str | None = None) -> list[StrategyRecord]:
        stmt = select(StrategyRecord)
        if status is not None:
            stmt = stmt.where(StrategyRecord.status == status)
        return list(session.scalars(stmt).all())

    def update_status(self, session: Session, strategy_id: int, status: str) -> None:
        record = session.get(StrategyRecord, strategy_id)
        if record is not None:
            record.status = status
            session.flush()

    def delete(self, session: Session, strategy_id: int) -> None:
        record = session.get(StrategyRecord, strategy_id)
        if record is not None:
            session.delete(record)
            session.flush()

class BacktestRepository:
    def save(self, session: Session, record: BacktestRecord) -> BacktestRecord:
        session.add(record)
        session.flush()
        return record

    def get(self, session: Session, backtest_id: int) -> BacktestRecord | None:
        return session.get(BacktestRecord, backtest_id)

    def get_by_strategy(self, session: Session, strategy_id: int) -> list[BacktestRecord]:
        stmt = select(BacktestRecord).where(BacktestRecord.strategy_id == strategy_id)
        return list(session.scalars(stmt).all())

    def list_all(self, session: Session) -> list[BacktestRecord]:
        stmt = select(BacktestRecord)
        return list(session.scalars(stmt).all())

    def get_history(
        self, session: Session, strategy_id: int, limit: int = 100
    ) -> list[BacktestRecord]:
        """Return time-ordered history for a strategy (newest first)."""
        stmt = (
            select(BacktestRecord)
            .where(BacktestRecord.strategy_id == strategy_id)
            .order_by(BacktestRecord.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    def compare_strategies(
        self, session: Session, strategy_ids: list[int]
    ) -> list[BacktestRecord]:
        """Return most recent backtest per strategy for cross-comparison."""
        if not strategy_ids:
            return []
        stmt = (
            select(BacktestRecord)
            .where(BacktestRecord.strategy_id.in_(strategy_ids))
            .order_by(BacktestRecord.created_at.desc())
        )
        return list(session.scalars(stmt).all())

    def delete(self, session: Session, backtest_id: int) -> None:
        """Delete a single backtest record."""
        record = session.get(BacktestRecord, backtest_id)
        if record is not None:
            session.delete(record)
            session.flush()

    def delete_by_strategy(self, session: Session, strategy_id: int) -> None:
        """Delete all backtest records for a strategy."""
        records = self.get_by_strategy(session, strategy_id)
        for record in records:
            session.delete(record)
        session.flush()

class KnowledgeRepository:
    def save(self, session: Session, record: KnowledgeRecord) -> KnowledgeRecord:
        session.add(record)
        session.flush()
        return record

    def search(
        self, session: Session, query: str | None = None, tag: str | None = None
    ) -> list[KnowledgeRecord]:
        stmt = select(KnowledgeRecord)
        results = list(session.scalars(stmt).all())

        if query:
            q = query.lower()
            results = [r for r in results if q in r.title.lower() or q in r.source.lower()]

        if tag:
            results = [r for r in results if tag in json.loads(r.tags_json)]

        return results

    def get_by_tag(self, session: Session, tag: str) -> list[KnowledgeRecord]:
        stmt = select(KnowledgeRecord)
        all_records = list(session.scalars(stmt).all())
        return [r for r in all_records if tag in json.loads(r.tags_json)]


class TradeRepository:
    """포지션 단위 거래 기록 저장소."""

    def save(self, session: Session, record: TradeRecord) -> TradeRecord:
        session.add(record)
        session.flush()
        return record

    def get_by_trade_id(self, session: Session, trade_id: str) -> TradeRecord | None:
        stmt = select(TradeRecord).where(TradeRecord.trade_id == trade_id)
        return session.scalars(stmt).first()

    def list_open(
        self,
        session: Session,
        symbol: str | None = None,
        strategy_name: str | None = None,
        broker: str | None = None,
    ) -> list[TradeRecord]:
        stmt = select(TradeRecord).where(TradeRecord.status == "open")
        if symbol:
            stmt = stmt.where(TradeRecord.symbol == symbol)
        if strategy_name:
            stmt = stmt.where(TradeRecord.strategy_name == strategy_name)
        if broker:
            stmt = stmt.where(TradeRecord.broker == broker)
        return list(session.scalars(stmt).all())

    def list_closed(
        self,
        session: Session,
        symbol: str | None = None,
        strategy_name: str | None = None,
        broker: str | None = None,
        limit: int = 100,
    ) -> list[TradeRecord]:
        stmt = select(TradeRecord).where(TradeRecord.status == "closed")
        if symbol:
            stmt = stmt.where(TradeRecord.symbol == symbol)
        if strategy_name:
            stmt = stmt.where(TradeRecord.strategy_name == strategy_name)
        if broker:
            stmt = stmt.where(TradeRecord.broker == broker)
        stmt = stmt.order_by(TradeRecord.exit_at.desc()).limit(limit)
        return list(session.scalars(stmt).all())

    def close_trade(
        self,
        session: Session,
        trade_id: str,
        exit_price: float,
        exit_quantity: float,
        exit_fee: float,
        exit_reason: str,
        exit_at: "datetime",
    ) -> TradeRecord | None:
        record = self.get_by_trade_id(session, trade_id)
        if record is None or record.status != "open":
            return None

        record.exit_price = exit_price
        record.exit_quantity = exit_quantity
        record.exit_fee = exit_fee
        record.exit_reason = exit_reason
        record.exit_at = exit_at
        record.status = "closed"

        # 손익 계산
        if record.side == "long":
            record.profit_abs = (exit_price - record.entry_price) * exit_quantity - record.entry_fee - exit_fee
        else:
            record.profit_abs = (record.entry_price - exit_price) * exit_quantity - record.entry_fee - exit_fee

        record.profit_pct = round(record.profit_abs / record.stake_amount * 100, 4) if record.stake_amount else 0.0
        record.duration_seconds = int((exit_at - record.entry_at).total_seconds())
        session.flush()
        return record

    def summary(
        self,
        session: Session,
        strategy_name: str | None = None,
        broker: str | None = None,
    ) -> dict:
        """거래 성과 요약."""
        trades = self.list_closed(session, strategy_name=strategy_name, broker=broker, limit=10000)
        if not trades:
            return {"total": 0}

        wins = [t for t in trades if (t.profit_abs or 0) > 0]
        losses = [t for t in trades if (t.profit_abs or 0) <= 0]
        total_profit = sum(t.profit_abs or 0 for t in trades)
        avg_profit_pct = sum(t.profit_pct or 0 for t in trades) / len(trades)

        return {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_profit": round(total_profit, 0),
            "avg_profit_pct": round(avg_profit_pct, 2),
            "best_trade": round(max((t.profit_pct or 0) for t in trades), 2),
            "worst_trade": round(min((t.profit_pct or 0) for t in trades), 2),
        }


class OrderRepository:
    """주문 단위 기록 저장소."""

    def save(self, session: Session, record: OrderRecord) -> OrderRecord:
        session.add(record)
        session.flush()
        return record

    def get_by_order_id(self, session: Session, order_id: str) -> OrderRecord | None:
        stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
        return session.scalars(stmt).first()

    def list_by_trade(self, session: Session, trade_id: int) -> list[OrderRecord]:
        stmt = select(OrderRecord).where(OrderRecord.trade_id == trade_id).order_by(OrderRecord.created_at)
        return list(session.scalars(stmt).all())

    def update_status(
        self,
        session: Session,
        order_id: str,
        status: str,
        filled: float | None = None,
    ) -> OrderRecord | None:
        record = self.get_by_order_id(session, order_id)
        if record is None:
            return None
        record.status = status
        if filled is not None:
            record.filled = filled
            record.remaining = record.amount - filled
        session.flush()
        return record


class PaperRepository:
    """Paper trading 잔고/PnL 스냅샷 저장소."""

    def save_balance(self, session: Session, record: PaperBalance) -> PaperBalance:
        session.add(record)
        session.flush()
        return record

    def get_latest_balance(
        self, session: Session, strategy_id: str,
    ) -> PaperBalance | None:
        stmt = (
            select(PaperBalance)
            .where(PaperBalance.strategy_id == strategy_id)
            .order_by(PaperBalance.snapshot_at.desc())
            .limit(1)
        )
        return session.scalars(stmt).first()

    def save_daily_snapshot(
        self, session: Session, record: PaperPnlSnapshot,
    ) -> PaperPnlSnapshot:
        """Upsert: 같은 (strategy_id, date) 존재 시 UPDATE."""
        existing = session.scalars(
            select(PaperPnlSnapshot).where(
                PaperPnlSnapshot.strategy_id == record.strategy_id,
                PaperPnlSnapshot.date == record.date,
            )
        ).first()

        if existing is not None:
            existing.cumulative_pnl = record.cumulative_pnl
            existing.daily_pnl = record.daily_pnl
            existing.trade_count = record.trade_count
            existing.win_count = record.win_count
            existing.equity = record.equity
            session.flush()
            return existing

        session.add(record)
        session.flush()
        return record

    def get_daily_snapshots(
        self, session: Session, strategy_id: str, limit: int = 90,
    ) -> list[PaperPnlSnapshot]:
        stmt = (
            select(PaperPnlSnapshot)
            .where(PaperPnlSnapshot.strategy_id == strategy_id)
            .order_by(PaperPnlSnapshot.date.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    def get_paper_strategies(self, session: Session) -> list[str]:
        stmt = (
            select(PaperPnlSnapshot.strategy_id)
            .distinct()
        )
        return list(session.scalars(stmt).all())

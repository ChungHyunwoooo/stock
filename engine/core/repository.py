
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.schema import StrategyDefinition
from engine.core.db_models import BacktestRecord, KnowledgeRecord, StrategyRecord

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

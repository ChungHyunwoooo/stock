"""로컬 모의거래 브로커 (DB 영속화).

거래소 API 호출 없이 즉시 체결 시뮬레이션.
프로세스 재시작 시 잔고/포지션 복원.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from engine.core.models import BrokerKind, ExecutionRecord, OrderRequest
from engine.execution.broker_base import BaseBroker

logger = logging.getLogger(__name__)


class PaperBroker(BaseBroker):
    """로컬 모의거래 브로커 (즉시 체결, DB 영속화)."""

    exchange_name = "paper"
    market_type = "spot"
    broker_kind = BrokerKind.paper

    def __init__(
        self,
        strategy_id: str = "default",
        initial_balance: float = 10_000_000,
        db_url: str | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        self._initial_balance = initial_balance
        self._db_url = db_url
        self._positions: list[dict[str, Any]] = []

        # DB 초기화
        self._ensure_db(db_url)

        # DB에서 잔고 복원 시도
        self._balance = self._restore_balance()

    def _ensure_db(self, db_url: str | None) -> None:
        """DB 엔진 초기화 (필요 시)."""
        if db_url is not None:
            import engine.core.database as _db
            from engine.core.db_models import Base

            # Reset singleton if db_url differs from current engine
            if _db._engine is not None:
                current_url = str(_db._engine.url)
                if current_url != db_url:
                    _db._engine.dispose()
                    _db._engine = None

            engine = _db.get_engine(db_url)
            Base.metadata.create_all(engine)
            _db._migrate_paper_phase3(engine)

    def _restore_balance(self) -> float:
        """DB에서 최신 잔고 복원. 없으면 initial_balance."""
        try:
            from engine.core.database import get_session
            from engine.core.repository import PaperRepository

            repo = PaperRepository()
            with get_session() as session:
                latest = repo.get_latest_balance(session, self.strategy_id)
                if latest is not None:
                    logger.info(
                        "[paper] Restored balance for %s: %.2f",
                        self.strategy_id, latest.balance,
                    )
                    return latest.balance
        except Exception:
            logger.warning(
                "[paper] Failed to restore balance for %s, using initial",
                self.strategy_id, exc_info=True,
            )
        return self._initial_balance

    def _save_balance_snapshot(self) -> None:
        """현재 잔고를 DB에 스냅샷 저장. DB 실패 시 무시."""
        try:
            from engine.core.database import get_session
            from engine.core.db_models import PaperBalance
            from engine.core.repository import PaperRepository

            repo = PaperRepository()
            record = PaperBalance(
                strategy_id=self.strategy_id,
                balance=self._balance,
                equity=self._balance,
                unrealized_pnl=0.0,
                snapshot_at=datetime.now(timezone.utc),
            )
            with get_session() as session:
                repo.save_balance(session, record)
        except Exception:
            logger.warning(
                "[paper] Failed to save balance snapshot for %s",
                self.strategy_id, exc_info=True,
            )

    def _place_order(
        self, order: OrderRequest, converted_symbol: str,
    ) -> ExecutionRecord:
        result = self._build_execution_record(
            order,
            status="filled",
            notes="paper",
        )

        # 잔고 업데이트: 매수 시 차감, 매도 시 가산
        order_value = order.price * order.quantity
        if order.side.value == "long":
            self._balance -= order_value
        else:
            self._balance += order_value

        # DB에 잔고 스냅샷 저장 (실패해도 거래 계속)
        self._save_balance_snapshot()

        return result

    def save_daily_snapshot(self) -> None:
        """당일 거래 집계를 PaperPnlSnapshot에 upsert."""
        try:
            from engine.core.database import get_session
            from engine.core.db_models import PaperPnlSnapshot
            from engine.core.repository import PaperRepository, TradeRepository

            repo = PaperRepository()
            trade_repo = TradeRepository()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            with get_session() as session:
                # 전체 closed paper 거래
                all_closed = trade_repo.list_closed(
                    session,
                    strategy_name=self.strategy_id,
                    broker="paper",
                    limit=100_000,
                )

                cumulative_pnl = sum(t.profit_abs or 0 for t in all_closed)
                today_trades = [
                    t for t in all_closed
                    if t.exit_at and t.exit_at.strftime("%Y-%m-%d") == today
                ]
                daily_pnl = sum(t.profit_abs or 0 for t in today_trades)
                trade_count = len(all_closed)
                win_count = sum(1 for t in all_closed if (t.profit_abs or 0) > 0)

                snap = PaperPnlSnapshot(
                    strategy_id=self.strategy_id,
                    date=today,
                    cumulative_pnl=cumulative_pnl,
                    daily_pnl=daily_pnl,
                    trade_count=trade_count,
                    win_count=win_count,
                    equity=self._balance,
                )
                repo.save_daily_snapshot(session, snap)
        except Exception:
            logger.warning(
                "[paper] Failed to save daily snapshot for %s",
                self.strategy_id, exc_info=True,
            )

    def _fetch_raw_balance(self) -> dict[str, Any]:
        used = sum(
            p["entry_price"] * p["quantity"]
            for p in self._positions
        )
        return {
            "currency": "KRW",
            "total_equity": self._balance,
            "available": self._balance - used,
            "used": used,
            "unrealized_pnl": 0.0,
        }

    def _fetch_raw_positions(self) -> list[dict[str, Any]]:
        return list(self._positions)

    def _cancel_raw(self, order_id: str, converted_symbol: str) -> bool:
        return True

    def _convert_symbol(self, symbol: str) -> str:
        return symbol

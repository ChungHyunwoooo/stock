"""TradeRepository + OrderRepository 테스트."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import Base, OrderRecord, TradeRecord
from engine.core.repository import OrderRepository, TradeRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


@pytest.fixture
def trade_repo():
    return TradeRepository()


@pytest.fixture
def order_repo():
    return OrderRepository()


def _make_trade(
    trade_id: str = "t001",
    symbol: str = "KRW-BTC",
    side: str = "long",
    entry_price: float = 50_000_000,
    entry_quantity: float = 0.01,
    status: str = "open",
    broker: str = "paper",
    strategy_name: str = "double_bottom",
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe="1h",
        side=side,
        broker=broker,
        entry_price=entry_price,
        entry_quantity=entry_quantity,
        entry_fee=500,
        entry_tag="double_bottom",
        entry_at=datetime(2026, 1, 1, 10, 0),
        stake_amount=entry_price * entry_quantity,
        stop_loss=49_000_000,
        take_profit=52_000_000,
        status=status,
        signal_id="sig001",
    )


def _make_order(
    order_id: str = "o001",
    trade_id: int = 1,
    side: str = "buy",
    price: float = 50_000_000,
    amount: float = 0.01,
    is_entry: bool = True,
) -> OrderRecord:
    return OrderRecord(
        order_id=order_id,
        trade_id=trade_id,
        side=side,
        order_type="market",
        price=price,
        amount=amount,
        filled=amount,
        remaining=0.0,
        fee=500,
        status="filled",
        is_entry=is_entry,
    )


# ── TradeRepository ─────────────────────────────────────────


class TestTradeRepository:
    def test_save_and_get(self, session, trade_repo):
        trade = _make_trade()
        trade_repo.save(session, trade)
        session.commit()

        result = trade_repo.get_by_trade_id(session, "t001")
        assert result is not None
        assert result.symbol == "KRW-BTC"
        assert result.side == "long"
        assert result.status == "open"

    def test_list_open(self, session, trade_repo):
        trade_repo.save(session, _make_trade("t001"))
        trade_repo.save(session, _make_trade("t002", symbol="KRW-ETH"))
        trade_repo.save(session, _make_trade("t003", status="closed"))
        session.commit()

        opens = trade_repo.list_open(session)
        assert len(opens) == 2

        btc_opens = trade_repo.list_open(session, symbol="KRW-BTC")
        assert len(btc_opens) == 1

    def test_close_trade_long(self, session, trade_repo):
        trade_repo.save(session, _make_trade("t001"))
        session.commit()

        exit_at = datetime(2026, 1, 1, 14, 0)
        result = trade_repo.close_trade(
            session,
            trade_id="t001",
            exit_price=51_000_000,
            exit_quantity=0.01,
            exit_fee=510,
            exit_reason="signal",
            exit_at=exit_at,
        )
        session.commit()

        assert result is not None
        assert result.status == "closed"
        assert result.exit_price == 51_000_000
        assert result.exit_reason == "signal"
        # profit = (51M - 50M) * 0.01 - 500 - 510 = 10000 - 1010 = 8990
        assert result.profit_abs == pytest.approx(8990, abs=1)
        assert result.profit_pct > 0
        assert result.duration_seconds == 4 * 3600

    def test_close_trade_short(self, session, trade_repo):
        trade_repo.save(session, _make_trade("t001", side="short"))
        session.commit()

        result = trade_repo.close_trade(
            session,
            trade_id="t001",
            exit_price=49_000_000,
            exit_quantity=0.01,
            exit_fee=490,
            exit_reason="stoploss",
            exit_at=datetime(2026, 1, 1, 12, 0),
        )
        session.commit()

        assert result is not None
        # profit = (50M - 49M) * 0.01 - 500 - 490 = 10000 - 990 = 9010
        assert result.profit_abs == pytest.approx(9010, abs=1)

    def test_close_nonexistent(self, session, trade_repo):
        result = trade_repo.close_trade(
            session, "nope", 50_000_000, 0.01, 0, "manual",
            datetime(2026, 1, 1),
        )
        assert result is None

    def test_close_already_closed(self, session, trade_repo):
        trade_repo.save(session, _make_trade("t001", status="closed"))
        session.commit()
        result = trade_repo.close_trade(
            session, "t001", 50_000_000, 0.01, 0, "manual",
            datetime(2026, 1, 1),
        )
        assert result is None

    def test_list_closed_filters(self, session, trade_repo):
        for i, (sym, strat, brk) in enumerate([
            ("KRW-BTC", "double_bottom", "paper"),
            ("KRW-ETH", "pullback", "paper"),
            ("KRW-BTC", "double_bottom", "live"),
        ]):
            t = _make_trade(f"t{i}", symbol=sym, strategy_name=strat, broker=brk, status="closed")
            t.exit_price = 51_000_000
            t.exit_at = datetime(2026, 1, 2)
            t.profit_abs = 10000
            t.profit_pct = 2.0
            trade_repo.save(session, t)
        session.commit()

        assert len(trade_repo.list_closed(session)) == 3
        assert len(trade_repo.list_closed(session, symbol="KRW-BTC")) == 2
        assert len(trade_repo.list_closed(session, strategy_name="pullback")) == 1
        assert len(trade_repo.list_closed(session, broker="live")) == 1

    def test_summary(self, session, trade_repo):
        # 2 wins, 1 loss
        for i, profit in enumerate([10000, 5000, -3000]):
            t = _make_trade(f"t{i}", status="closed")
            t.exit_price = 51_000_000
            t.exit_at = datetime(2026, 1, 2)
            t.profit_abs = profit
            t.profit_pct = profit / 500_000 * 100
            trade_repo.save(session, t)
        session.commit()

        s = trade_repo.summary(session)
        assert s["total"] == 3
        assert s["wins"] == 2
        assert s["losses"] == 1
        assert s["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert s["total_profit"] == 12000

    def test_summary_empty(self, session, trade_repo):
        s = trade_repo.summary(session)
        assert s["total"] == 0


# ── OrderRepository ──────────────────────────────────────────


class TestOrderRepository:
    def test_save_and_get(self, session, trade_repo, order_repo):
        trade_repo.save(session, _make_trade("t001"))
        session.flush()

        order = _make_order("o001", trade_id=1)
        order_repo.save(session, order)
        session.commit()

        result = order_repo.get_by_order_id(session, "o001")
        assert result is not None
        assert result.side == "buy"
        assert result.status == "filled"

    def test_list_by_trade(self, session, trade_repo, order_repo):
        trade_repo.save(session, _make_trade("t001"))
        session.flush()

        order_repo.save(session, _make_order("o001", trade_id=1, is_entry=True))
        order_repo.save(session, _make_order("o002", trade_id=1, side="sell", is_entry=False))
        session.commit()

        orders = order_repo.list_by_trade(session, trade_id=1)
        assert len(orders) == 2
        assert orders[0].is_entry is True
        assert orders[1].is_entry is False

    def test_update_status(self, session, trade_repo, order_repo):
        trade_repo.save(session, _make_trade("t001"))
        session.flush()

        order = _make_order("o001", trade_id=1)
        order.status = "pending"
        order.filled = 0.0
        order.remaining = 0.01
        order_repo.save(session, order)
        session.commit()

        result = order_repo.update_status(session, "o001", "filled", filled=0.01)
        session.commit()

        assert result is not None
        assert result.status == "filled"
        assert result.filled == 0.01
        assert result.remaining == 0.0

    def test_update_nonexistent(self, session, order_repo):
        result = order_repo.update_status(session, "nope", "filled")
        assert result is None

    def test_trade_order_relationship(self, session, trade_repo, order_repo):
        """Trade.orders relationship 확인."""
        trade_repo.save(session, _make_trade("t001"))
        session.flush()

        order_repo.save(session, _make_order("o001", trade_id=1))
        order_repo.save(session, _make_order("o002", trade_id=1, side="sell"))
        session.commit()

        trade = trade_repo.get_by_trade_id(session, "t001")
        assert len(trade.orders) == 2

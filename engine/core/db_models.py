
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class StrategyRecord(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    definition_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

class BacktestRecord(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    symbol: Mapped[str] = mapped_column(String(50))
    timeframe: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    total_return: Mapped[float] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Phase 2 columns
    slippage_model: Mapped[str] = mapped_column(String(50), default="none")
    fee_rate: Mapped[float] = mapped_column(Float, default=0.0)
    wf_result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cpcv_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    multi_symbol_result: Mapped[str | None] = mapped_column(Text, nullable=True)

class KnowledgeRecord(Base):
    __tablename__ = "knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(500), unique=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    category: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 거래 기록 ───────────────────────────────────────────────


class TradeRecord(Base):
    """포지션 단위 거래 기록.

    하나의 Trade = 진입~청산 사이클.
    Trade 1 : N OrderRecord.
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(200), index=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    side: Mapped[str] = mapped_column(String(10))  # long / short
    broker: Mapped[str] = mapped_column(String(10), default="paper")  # paper / live

    # 진입
    entry_price: Mapped[float] = mapped_column(Float)
    entry_quantity: Mapped[float] = mapped_column(Float)
    entry_fee: Mapped[float] = mapped_column(Float, default=0.0)
    entry_tag: Mapped[str] = mapped_column(String(200), default="")  # 트리거 패턴명
    entry_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    # 청산 (open 상태면 NULL)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_fee: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str] = mapped_column(String(50), default="")  # signal/stoploss/trailing/manual/tp
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 손익
    profit_abs: Mapped[float | None] = mapped_column(Float, nullable=True)  # 절대 수익 (KRW)
    profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 수익률 (%)
    stake_amount: Mapped[float] = mapped_column(Float, default=0.0)  # 투입금

    # 리스크
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 상태
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open/closed/cancelled
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal_id: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationship
    orders: Mapped[list["OrderRecord"]] = relationship(back_populates="trade", cascade="all, delete-orphan")


class OrderRecord(Base):
    """주문 단위 기록.

    Trade에 N:1. 진입 주문, 청산 주문, 부분 청산 등 개별 추적.
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)

    side: Mapped[str] = mapped_column(String(10))  # buy / sell
    order_type: Mapped[str] = mapped_column(String(20), default="market")  # market/limit
    price: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    filled: Mapped[float] = mapped_column(Float, default=0.0)
    remaining: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/filled/partial/cancelled/expired
    is_entry: Mapped[bool] = mapped_column(Boolean, default=True)  # True=진입, False=청산

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationship
    trade: Mapped["TradeRecord"] = relationship(back_populates="orders")

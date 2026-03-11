"""Tests for Paper Trading Discord plugin and API router."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.core.db_models import Base, PaperPnlSnapshot, TradeRecord
from engine.core.repository import PaperRepository, TradeRepository
from engine.interfaces.discord.commands.paper_trading import (
    PaperTradingPlugin,
    PromotionConfirmView,
    _build_promotion_embed,
    _build_status_embed,
    _build_summary_embed,
)
from engine.strategy.promotion_gate import (
    PromotionCheck,
    PromotionConfig,
    PromotionGate,
    PromotionResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    yield session
    session.close()


def _seed_data(session: Session, strategy_id: str, days: int = 10, trades: int = 15):
    """Seed snapshot and trade data for testing."""
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        session.add(PaperPnlSnapshot(
            strategy_id=strategy_id,
            date=d.isoformat(),
            cumulative_pnl=50.0 * (i + 1),
            daily_pnl=50.0,
            trade_count=i + 1,
            win_count=max(1, (i + 1) * 2 // 3),
            equity=10000 + 50.0 * (i + 1),
        ))

    now = datetime.now(timezone.utc)
    for i in range(trades):
        is_win = i < int(trades * 0.6)
        session.add(TradeRecord(
            trade_id=f"trade_{strategy_id}_{i}",
            strategy_name=strategy_id,
            symbol="BTC/USDT",
            timeframe="1h",
            side="long",
            broker="paper",
            entry_price=50000.0,
            entry_quantity=0.01,
            entry_fee=0.5,
            entry_at=now - timedelta(hours=trades - i),
            exit_price=51000.0 if is_win else 49000.0,
            exit_quantity=0.01,
            exit_fee=0.5,
            exit_reason="signal",
            exit_at=now - timedelta(hours=trades - i - 1),
            profit_abs=10.0 if is_win else -10.0,
            profit_pct=2.0 if is_win else -2.0,
            stake_amount=500.0,
            status="closed",
        ))
    session.flush()


# ---------------------------------------------------------------------------
# Embed builder tests
# ---------------------------------------------------------------------------


class TestEmbedBuilders:
    def test_build_status_embed(self):
        result = PromotionResult(
            passed=True,
            checks={
                "days": PromotionCheck(name="운영 기간", required=7, actual=10, passed=True),
                "trades": PromotionCheck(name="거래 수", required=10, actual=15, passed=True),
            },
            summary="모든 기준 충족",
        )
        embed = _build_status_embed("test_strat", result, days=10, trades=15)
        assert "test_strat" in embed.title
        assert embed.color.value == 0x2ECC71

    def test_build_status_embed_failing(self):
        result = PromotionResult(
            passed=False,
            checks={
                "days": PromotionCheck(name="운영 기간", required=7, actual=3, passed=False),
            },
            summary="미충족: 운영 기간",
        )
        embed = _build_status_embed("test_strat", result, days=3, trades=5)
        assert embed.color.value == 0xF39C12

    def test_build_summary_embed_empty(self):
        embed = _build_summary_embed([])
        assert "없음" in embed.description

    def test_build_summary_embed_with_items(self):
        items = [
            {"strategy_id": "s1", "days": 10, "trades": 15, "cumulative_pnl": 500.0, "readiness": "6/6", "passed": True},
        ]
        embed = _build_summary_embed(items)
        assert "s1" in embed.description

    def test_build_promotion_embed_passed(self):
        result = PromotionResult(
            passed=True,
            checks={"days": PromotionCheck(name="운영 기간", required=7, actual=10, passed=True)},
            summary="모든 기준 충족",
        )
        embed = _build_promotion_embed("test", result)
        assert embed.color.value == 0x2ECC71

    def test_build_promotion_embed_failed(self):
        result = PromotionResult(
            passed=False,
            checks={"days": PromotionCheck(name="운영 기간", required=7, actual=3, passed=False)},
            summary="미충족: 운영 기간",
            estimated_promotion="기간 4일 남음",
        )
        embed = _build_promotion_embed("test", result)
        assert embed.color.value == 0xE74C3C


# ---------------------------------------------------------------------------
# Plugin registration test
# ---------------------------------------------------------------------------


class TestPaperTradingPlugin:
    def test_plugin_has_name(self):
        plugin = PaperTradingPlugin()
        assert plugin.name == "paper_trading"

    def test_plugin_registers_commands(self):
        plugin = PaperTradingPlugin()
        tree = MagicMock()
        context = MagicMock()
        plugin.register(tree, context)
        # tree.command should have been called (as decorator)
        assert tree.command.called


# ---------------------------------------------------------------------------
# PromotionConfirmView test
# ---------------------------------------------------------------------------


class TestPromotionConfirmView:
    def test_view_has_buttons(self):
        context = MagicMock()
        gate = MagicMock()
        config = PromotionConfig()
        view = PromotionConfirmView("test", context, gate, config)
        # View should have children (buttons)
        assert len(view.children) == 2


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


class TestImports:
    def test_default_plugins_includes_paper_trading(self):
        from engine.interfaces.discord.commands import DEFAULT_COMMAND_PLUGINS
        names = [p.name for p in DEFAULT_COMMAND_PLUGINS]
        assert "paper_trading" in names

    def test_api_router_paper_importable(self):
        from api.routers import paper
        assert hasattr(paper, "router")

"""Discord /페이퍼현황, /전략승격 slash command plugin -- paper trading status and promotion."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import discord
from discord import Interaction, app_commands

from engine.core.database import get_session
from engine.core.repository import PaperRepository, TradeRepository
from engine.interfaces.discord.context import DiscordBotContext
from engine.strategy.lifecycle_manager import InvalidTransitionError, StrategyNotFoundError
from engine.strategy.promotion_gate import (
    PromotionConfig,
    PromotionGate,
    PromotionResult,
    resolve_promotion_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_global_config() -> dict:
    try:
        path = Path("config/paper_trading.json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _build_status_embed(strategy_id: str, result: PromotionResult, days: int, trades: int) -> discord.Embed:
    """Build paper status embed for a single strategy."""
    color = 0x2ECC71 if result.passed else 0xF39C12
    embed = discord.Embed(title=f"페이퍼 현황 -- {strategy_id}", color=color)

    lines: list[str] = []
    for key, check in result.checks.items():
        icon = "OK" if check.passed else "NG"
        actual_str = f"{check.actual}" if check.actual is not None else "N/A"
        lines.append(f"{check.name}: {actual_str} {'>=  ' if key != 'max_drawdown' else '>= '}{check.required} {icon}")

    embed.add_field(name="운영일수", value=str(days), inline=True)
    embed.add_field(name="거래수", value=str(trades), inline=True)
    embed.add_field(
        name="승격 진행률",
        value=f"{sum(1 for c in result.checks.values() if c.passed)}/{len(result.checks)}",
        inline=True,
    )
    embed.add_field(name="상세 기준", value="```\n" + "\n".join(lines) + "\n```", inline=False)

    if result.estimated_promotion:
        embed.set_footer(text=f"예상: {result.estimated_promotion}")

    return embed


def _build_summary_embed(items: list[dict]) -> discord.Embed:
    """Build summary embed for all paper strategies."""
    embed = discord.Embed(title="페이퍼 전략 현황", color=0x3498DB)
    if not items:
        embed.description = "Paper 상태 전략 없음"
        return embed

    lines: list[str] = []
    for item in items:
        status = "OK" if item["passed"] else "NG"
        lines.append(
            f"{item['strategy_id']:<20} | D{item['days']:>3} | T{item['trades']:>3} | "
            f"PnL {item['cumulative_pnl']:>8.0f} | {item['readiness']} {status}"
        )
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    return embed


def _build_promotion_embed(strategy_id: str, result: PromotionResult) -> discord.Embed:
    """Build promotion evaluation result embed."""
    color = 0x2ECC71 if result.passed else 0xE74C3C
    embed = discord.Embed(
        title=f"승격 평가 -- {strategy_id}",
        description=result.summary,
        color=color,
    )

    lines: list[str] = []
    for check in result.checks.values():
        icon = "OK" if check.passed else "NG"
        actual_str = f"{check.actual}" if check.actual is not None else "N/A"
        lines.append(f"{check.name}: {actual_str} (기준: {check.required}) {icon}")

    embed.add_field(name="기준 검증", value="```\n" + "\n".join(lines) + "\n```", inline=False)

    if result.estimated_promotion:
        embed.add_field(name="예상 승격 시점", value=result.estimated_promotion, inline=False)

    return embed


# ---------------------------------------------------------------------------
# Promotion Confirm View
# ---------------------------------------------------------------------------

class PromotionConfirmView(discord.ui.View):
    """Confirm / Cancel buttons for strategy promotion."""

    def __init__(
        self,
        strategy_id: str,
        context: DiscordBotContext,
        gate: PromotionGate,
        gate_config: PromotionConfig,
    ) -> None:
        super().__init__(timeout=120)
        self.strategy_id = strategy_id
        self.context = context
        self.gate = gate
        self.gate_config = gate_config

    @discord.ui.button(label="승격 확인", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: discord.ui.Button) -> None:
        try:
            with get_session() as session:
                result = self.context.lifecycle_manager.transition(
                    self.strategy_id,
                    "active",
                    reason="Discord 승격 커맨드",
                    gate=self.gate,
                    gate_config=self.gate_config,
                    session=session,
                )

                # Record promotion snapshot in notes
                entry = self.context.lifecycle_manager.get_strategy(self.strategy_id)

            embed = discord.Embed(
                title="승격 완료",
                description=f"전략 **{result.get('name', self.strategy_id)}**가 `paper` -> `active`로 승격되었습니다.",
                color=0x2ECC71,
            )
            embed.add_field(name="전략 ID", value=self.strategy_id, inline=True)
            embed.add_field(name="새 상태", value="active", inline=True)
            await interaction.response.edit_message(embed=embed, view=None)
        except InvalidTransitionError as exc:
            embed = discord.Embed(
                title="승격 실패",
                description=str(exc),
                color=0xE74C3C,
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as exc:
            logger.exception("Promotion failed for %s", self.strategy_id)
            embed = discord.Embed(
                title="승격 오류",
                description=f"예상치 못한 오류: {exc}",
                color=0xE74C3C,
            )
            await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="승격이 취소되었습니다.", embed=None, view=None)


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------

# Test hook: override paper strategies list for testing
_paper_repo_override: PaperRepository | None = None


def _get_paper_repo() -> PaperRepository:
    return _paper_repo_override if _paper_repo_override is not None else PaperRepository()


async def paper_strategy_autocomplete(
    interaction: Interaction, current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete: list paper-status strategies."""
    try:
        repo = _get_paper_repo()
        with get_session() as session:
            strategies = repo.get_paper_strategies(session)
        needle = current.lower().strip()
        if needle:
            strategies = [s for s in strategies if needle in s.lower()]
        return [app_commands.Choice(name=s[:100], value=s) for s in strategies[:25]]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Command Plugin
# ---------------------------------------------------------------------------

class PaperTradingPlugin:
    """Registers /페이퍼현황 and /전략승격 slash commands."""

    name = "paper_trading"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        paper_repo = PaperRepository()
        trade_repo = TradeRepository()

        @tree.command(name="페이퍼현황", description="Paper 전략 성과 현황 조회")
        @app_commands.describe(strategy_id="전략 ID (미입력 시 전체 조회)")
        @app_commands.autocomplete(strategy_id=paper_strategy_autocomplete)
        async def paper_status(
            interaction: Interaction,
            strategy_id: str | None = None,
        ) -> None:
            await interaction.response.defer()

            gate = PromotionGate(paper_repo=paper_repo, trade_repo=trade_repo)
            global_config = _load_global_config()
            config = resolve_promotion_config(None, global_config)

            with get_session() as session:
                if strategy_id:
                    result = gate.evaluate(strategy_id, config, session)
                    snapshots = paper_repo.get_daily_snapshots(session, strategy_id, limit=9999)
                    trades_count = int(result.checks["trades"].actual) if result.checks.get("trades") and result.checks["trades"].actual is not None else 0
                    embed = _build_status_embed(strategy_id, result, len(snapshots), trades_count)
                else:
                    sids = paper_repo.get_paper_strategies(session)
                    items: list[dict] = []
                    for sid in sids:
                        r = gate.evaluate(sid, config, session)
                        snaps = paper_repo.get_daily_snapshots(session, sid, limit=9999)
                        checks = r.checks
                        passed_count = sum(1 for c in checks.values() if c.passed)
                        items.append({
                            "strategy_id": sid,
                            "days": len(snaps),
                            "trades": int(checks["trades"].actual) if checks.get("trades") and checks["trades"].actual is not None else 0,
                            "cumulative_pnl": checks["cumulative_pnl"].actual if checks.get("cumulative_pnl") and checks["cumulative_pnl"].actual is not None else 0.0,
                            "readiness": f"{passed_count}/{len(checks)}",
                            "passed": r.passed,
                        })
                    embed = _build_summary_embed(items)

            await interaction.followup.send(embed=embed)

        @tree.command(name="전략승격", description="Paper 전략을 Live로 승격")
        @app_commands.describe(strategy_id="승격할 전략 ID")
        @app_commands.autocomplete(strategy_id=paper_strategy_autocomplete)
        async def promote_strategy(
            interaction: Interaction,
            strategy_id: str,
        ) -> None:
            await interaction.response.defer(ephemeral=True)

            gate = PromotionGate(paper_repo=paper_repo, trade_repo=trade_repo)
            global_config = _load_global_config()
            config = resolve_promotion_config(None, global_config)

            with get_session() as session:
                result = gate.evaluate(strategy_id, config, session)

            embed = _build_promotion_embed(strategy_id, result)

            if result.passed:
                view = PromotionConfirmView(
                    strategy_id=strategy_id,
                    context=context,
                    gate=gate,
                    gate_config=config,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

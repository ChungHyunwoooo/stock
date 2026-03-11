"""Discord /전략전이 slash command plugin -- lifecycle state transitions."""

from __future__ import annotations

import discord
from discord import Interaction, app_commands

from engine.interfaces.discord.autocomplete import (
    strategy_autocomplete,
    target_status_autocomplete,
)
from engine.interfaces.discord.context import DiscordBotContext
from engine.strategy.lifecycle_manager import (
    InvalidTransitionError,
    StrategyNotFoundError,
)


# ---------------------------------------------------------------------------
# Embed builder
# ---------------------------------------------------------------------------

_COLOR_MAP: dict[str, int] = {
    "draft": 0x95A5A6,
    "testing": 0xF39C12,
    "paper": 0x3498DB,
    "active": 0x2ECC71,
    "archived": 0xE74C3C,
}


def build_transition_embed(
    strategy_name: str,
    strategy_id: str,
    from_status: str,
    to_status: str,
    history: list[dict],
) -> discord.Embed:
    """Build a Discord Embed summarising a completed transition."""
    embed = discord.Embed(
        title="전략 전이 완료",
        color=_COLOR_MAP.get(to_status, 0x000000),
    )
    embed.add_field(name="전략", value=f"{strategy_name} (`{strategy_id}`)", inline=False)
    embed.add_field(name="상태 변경", value=f"`{from_status}` \u2192 `{to_status}`", inline=True)
    embed.add_field(name="전이 이력", value=f"{len(history)}건", inline=True)
    return embed


def _build_error_embed(message: str) -> discord.Embed:
    """Build a red error embed."""
    return discord.Embed(title="전이 실패", description=message, color=0xE74C3C)


# ---------------------------------------------------------------------------
# Confirmation View
# ---------------------------------------------------------------------------

class TransitionConfirmView(discord.ui.View):
    """Confirm / Cancel buttons before executing a lifecycle transition."""

    def __init__(
        self,
        strategy_id: str,
        from_status: str,
        to_status: str,
        context: DiscordBotContext,
    ) -> None:
        super().__init__(timeout=60)
        self.strategy_id = strategy_id
        self.from_status = from_status
        self.to_status = to_status
        self.context = context

    @discord.ui.button(label="확인", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: discord.ui.Button) -> None:
        try:
            result = self.context.lifecycle_manager.transition(
                self.strategy_id, self.to_status, reason="Discord 커맨드",
            )
            embed = build_transition_embed(
                strategy_name=result.get("name", self.strategy_id),
                strategy_id=self.strategy_id,
                from_status=self.from_status,
                to_status=self.to_status,
                history=result.get("status_history", []),
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except InvalidTransitionError as exc:
            await interaction.response.edit_message(
                embed=_build_error_embed(str(exc)), view=None,
            )
        except StrategyNotFoundError as exc:
            await interaction.response.edit_message(
                embed=_build_error_embed(str(exc)), view=None,
            )

    @discord.ui.button(label="취소", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="전이가 취소되었습니다.", view=None)


# ---------------------------------------------------------------------------
# Command Plugin
# ---------------------------------------------------------------------------

class LifecycleCommandPlugin:
    """Registers the /전략전이 slash command."""

    name = "lifecycle"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="전략전이", description="전략 상태를 변경합니다")
        @app_commands.describe(
            strategy_id="전략 ID",
            target_status="목표 상태 (testing/paper/active/archived/draft)",
        )
        @app_commands.autocomplete(
            strategy_id=strategy_autocomplete,
            target_status=target_status_autocomplete,
        )
        async def transition(
            interaction: Interaction,
            strategy_id: str,
            target_status: str,
        ) -> None:
            try:
                entry = context.lifecycle_manager.get_strategy(strategy_id)
            except StrategyNotFoundError:
                await interaction.response.send_message(
                    embed=_build_error_embed(f"전략을 찾을 수 없습니다: {strategy_id}"),
                    ephemeral=True,
                )
                return

            from_status = entry.get("status", "unknown")
            view = TransitionConfirmView(
                strategy_id=strategy_id,
                from_status=from_status,
                to_status=target_status,
                context=context,
            )
            await interaction.response.send_message(
                content=f"전략 **{entry.get('name', strategy_id)}**를 "
                        f"`{from_status}` \u2192 `{target_status}`(으)로 전이합니다. 확인/취소",
                view=view,
                ephemeral=True,
            )

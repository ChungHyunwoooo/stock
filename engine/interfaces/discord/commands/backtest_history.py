"""Discord /백테스트이력 slash command plugin -- backtest history query."""

from __future__ import annotations

import discord
from discord import Interaction, app_commands

from engine.interfaces.discord.context import DiscordBotContext


def _build_history_embed(
    strategy_id: int, rows: list[dict]
) -> discord.Embed:
    embed = discord.Embed(
        title=f"백테스트 이력 — 전략 {strategy_id}",
        color=0x3498DB,
    )
    if not rows:
        embed.description = "이력 없음"
        return embed

    lines: list[str] = []
    for r in rows[:10]:
        ret = f"{r['total_return']:.2%}"
        sharpe = f"{r['sharpe_ratio']:.2f}" if r.get("sharpe_ratio") is not None else "-"
        lines.append(
            f"`{r['id']:>4}` | {r['symbol']:<10} | {ret:>8} | SR {sharpe}"
        )
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    embed.set_footer(text=f"{len(rows)}건 조회 (최대 10건 표시)")
    return embed


def _build_compare_embed(rows: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="전략 비교", color=0x2ECC71)
    if not rows:
        embed.description = "비교 대상 없음"
        return embed

    lines: list[str] = []
    for r in rows[:10]:
        ret = f"{r['total_return']:.2%}"
        sharpe = f"{r['sharpe_ratio']:.2f}" if r.get("sharpe_ratio") is not None else "-"
        lines.append(
            f"S{r['strategy_id']:>3} | {r['symbol']:<10} | {ret:>8} | SR {sharpe}"
        )
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    return embed


class BacktestHistoryPlugin:
    name = "backtest_history"

    def register(
        self, tree: app_commands.CommandTree, context: DiscordBotContext
    ) -> None:
        @tree.command(
            name="백테스트이력",
            description="전략별 백테스트 이력 조회",
        )
        @app_commands.describe(
            strategy_id="전략 ID",
            limit="최대 조회 건수 (기본 20)",
        )
        async def backtest_history(
            interaction: Interaction,
            strategy_id: int,
            limit: int = 20,
        ) -> None:
            await interaction.response.defer()
            from engine.backtest.history_cli import show_history

            rows = show_history(strategy_id, limit=limit)
            embed = _build_history_embed(strategy_id, rows)
            await interaction.followup.send(embed=embed)

        @tree.command(
            name="백테스트비교",
            description="여러 전략의 백테스트 결과 비교",
        )
        @app_commands.describe(
            strategy_ids="전략 ID 목록 (쉼표 구분, 예: 1,2,3)",
        )
        async def backtest_compare(
            interaction: Interaction,
            strategy_ids: str,
        ) -> None:
            await interaction.response.defer()
            from engine.backtest.history_cli import compare_strategies

            ids = [int(x.strip()) for x in strategy_ids.split(",") if x.strip()]
            rows = compare_strategies(ids)
            embed = _build_compare_embed(rows)
            await interaction.followup.send(embed=embed)

        @tree.command(
            name="백테스트삭제",
            description="백테스트 이력 삭제 (전략별 또는 단건)",
        )
        @app_commands.describe(
            strategy_id="전략 ID (전략 전체 삭제)",
            backtest_id="백테스트 ID (단건 삭제)",
        )
        async def backtest_delete(
            interaction: Interaction,
            strategy_id: int | None = None,
            backtest_id: int | None = None,
        ) -> None:
            await interaction.response.defer()
            from engine.backtest.history_cli import delete_history

            delete_history(strategy_id=strategy_id, backtest_id=backtest_id)
            if backtest_id is not None:
                msg = f"백테스트 #{backtest_id} 삭제 완료"
            elif strategy_id is not None:
                msg = f"전략 {strategy_id}의 백테스트 이력 전체 삭제 완료"
            else:
                msg = "삭제 대상을 지정해주세요 (strategy_id 또는 backtest_id)"
            await interaction.followup.send(msg)

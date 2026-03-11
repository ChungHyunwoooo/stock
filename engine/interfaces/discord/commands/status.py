
from discord import Interaction, app_commands

from engine.interfaces.discord.context import DiscordBotContext
from engine.interfaces.discord.formatting import format_status_embed


class StatusCommandPlugin:
    name = "status_v2"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="status", description="Show positions, daily PnL, strategy status")
        async def status(interaction: Interaction) -> None:
            await interaction.response.defer()
            msg = format_status_embed(context.control, context.lifecycle_manager)
            await interaction.followup.send(msg)

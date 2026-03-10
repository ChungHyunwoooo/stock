
from discord import Interaction, app_commands

from engine.application.trading.exceptions import PendingOrderNotFoundError
from engine.interfaces.discord.autocomplete import pending_id_autocomplete
from engine.interfaces.discord.context import DiscordBotContext
from engine.interfaces.discord.formatting import format_pending_list

class OrderCommandPlugin:
    name = "orders"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="pending", description="List pending approvals")
        async def pending(interaction: Interaction) -> None:
            await interaction.response.send_message(format_pending_list(context.control))

        @tree.command(name="approve", description="Approve a pending order")
        @app_commands.autocomplete(pending_id=pending_id_autocomplete)
        async def approve(interaction: Interaction, pending_id: str) -> None:
            try:
                context.control.approve_pending(pending_id)
            except PendingOrderNotFoundError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.send_message(f"approved={pending_id}")

        @tree.command(name="reject", description="Reject a pending order")
        @app_commands.autocomplete(pending_id=pending_id_autocomplete)
        async def reject(interaction: Interaction, pending_id: str) -> None:
            try:
                context.control.reject_pending(pending_id)
            except PendingOrderNotFoundError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.send_message(f"rejected={pending_id}")

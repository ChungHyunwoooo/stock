
from discord import Interaction, app_commands

from engine.core import TradingMode
from engine.interfaces.discord.autocomplete import mode_autocomplete
from engine.interfaces.discord.context import DiscordBotContext

class RuntimeCommandPlugin:
    name = "runtime"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="pause", description="Pause automated processing")
        async def pause(interaction: Interaction) -> None:
            state = context.control.pause()
            await interaction.response.send_message(f"paused={state.paused}")

        @tree.command(name="resume", description="Resume automated processing")
        async def resume(interaction: Interaction) -> None:
            state = context.control.resume()
            await interaction.response.send_message(f"paused={state.paused}")

        @tree.command(name="mode", description="Set trading mode")
        @app_commands.describe(mode="alert_only | semi_auto | auto")
        @app_commands.autocomplete(mode=mode_autocomplete)
        async def mode(interaction: Interaction, mode: str) -> None:
            try:
                trading_mode = TradingMode(mode)
            except ValueError:
                await interaction.response.send_message("invalid mode", ephemeral=True)
                return
            state = context.control.set_mode(trading_mode)
            await interaction.response.send_message(f"mode={state.mode.value}")

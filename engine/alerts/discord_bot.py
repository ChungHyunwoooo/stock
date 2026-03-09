"""Legacy Discord bot path intentionally disabled.

The old interactive bot was moved to `engine.legacy.alerts.discord_bot_legacy`.
Active runtime must use `engine.interfaces.discord.control_bot` instead.
"""

raise RuntimeError(
    "engine.alerts.discord_bot is disabled. Use engine.interfaces.discord.control_bot or "
    "engine.legacy.alerts.discord_bot_legacy explicitly."
)

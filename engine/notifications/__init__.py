"""알림 전송."""

# 순환 import 방지: discord_webhook ↔ charts
# 직접 import 필요 시 engine.notifications.discord_webhook에서 가져올 것


def __getattr__(name: str):
    if name in ("DiscordWebhookNotifier", "MemoryNotifier"):
        from engine.notifications.discord_webhook import (
            DiscordWebhookNotifier,
            MemoryNotifier,
        )
        return {"DiscordWebhookNotifier": DiscordWebhookNotifier, "MemoryNotifier": MemoryNotifier}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

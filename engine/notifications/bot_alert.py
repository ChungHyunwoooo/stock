"""봇 전용 Discord 알림 — BTC_선물_봇 + 알트_데일리_봇.

기존 discord_webhook.py와 독립. 단순 웹훅 전송만.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/discord.json")


def _get_webhook_url() -> str | None:
    """trade 웹훅 URL 로드."""
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return data.get("webhooks", {}).get("trade") or data.get("webhook_url")
    except Exception as e:
        logger.debug("웹훅 URL 로드 실패: %s", e)
        return None


def send_bot_alert(
    bot_name: str,
    action: str,
    details: dict,
    color: int = 0xF0B90B,
) -> bool:
    """봇 이벤트를 Discord로 전송.

    Args:
        bot_name: "BTC_선물_봇" or "알트_데일리_봇"
        action: "진입", "청산", "상태"
        details: 표시할 필드 dict
        color: embed 색상

    Returns:
        성공 여부
    """
    url = _get_webhook_url()
    if not url:
        logger.debug("Discord 웹훅 URL 없음 — 알림 스킵")
        return False

    # 색상 자동 결정
    if action == "진입":
        color = 0x0ECB81 if details.get("side") == "LONG" else 0xF6465D
        emoji = "🟢" if details.get("side") == "LONG" else "🔴"
    elif action == "청산":
        pnl = details.get("pnl_pct", 0)
        color = 0x0ECB81 if pnl > 0 else 0xF6465D
        emoji = "✅" if pnl > 0 else "❌"
    else:
        emoji = "ℹ️"

    fields = [
        {"name": k, "value": str(v), "inline": True}
        for k, v in details.items()
    ]

    embed = {
        "title": f"{emoji} [{bot_name}] {action}",
        "color": color,
        "fields": fields,
        "footer": {"text": f"{bot_name} | Paper Mode"},
    }

    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        logger.warning("Discord 알림 실패: %s", e)
        return False


def alert_entry(bot_name: str, symbol: str, side: str, price: float, **extra) -> bool:
    """진입 알림."""
    details = {"심볼": symbol, "방향": side, "진입가": f"${price:,.2f}"}
    details.update(extra)
    return send_bot_alert(bot_name, "진입", details)


def alert_exit(bot_name: str, symbol: str, side: str, entry: float, exit_price: float,
               pnl_pct: float, reason: str, **extra) -> bool:
    """청산 알림."""
    details = {
        "심볼": symbol,
        "방향": side,
        "진입": f"${entry:,.2f}",
        "청산": f"${exit_price:,.2f}",
        "PnL": f"{pnl_pct:+.2f}%",
        "사유": reason,
        "pnl_pct": pnl_pct,
    }
    details.update(extra)
    return send_bot_alert(bot_name, "청산", details)

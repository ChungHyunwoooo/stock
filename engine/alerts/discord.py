"""Discord webhook alert sender for trading signals."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "discord.json"

SIDE_EMOJI = {"LONG": "\U0001f7e2", "SHORT": "\U0001f534"}
STRATEGY_COLOR = {
    "S1_WATERMELON_BREAKOUT": 0xE91E63,
    "S2_STAIRCASE_BOUNCE": 0xFFEB3B,
    "S3_MOMENTUM": 0x2196F3,
    "S4_FUNDING_RATE": 0x9C27B0,
    "S5_BEAR_SHORT": 0xF44336,
    "S6_VOLUME_SPIKE_SCALP": 0x00BCD4,
    "S7_RSI_EXTREME": 0xFF9800,
    "S8_EMA_CROSS": 0x4CAF50,
    "S9_BB_SQUEEZE": 0x673AB7,
    "S10_KEY_LEVEL": 0x3F51B5,
    "S11_CANDLE_SURGE": 0xE91E63,
    "UPBIT_MEGA_PUMP": 0xFFD700,
    "UPBIT_TOMMY_MACD": 0x26A69A,
    "UPBIT_TOMMY_BB_RSI": 0xAB47BC,
}


@dataclass
class Signal:
    strategy: str
    symbol: str
    side: str  # LONG / SHORT
    entry: float
    stop_loss: float
    take_profits: list[float] = field(default_factory=list)
    leverage: int = 1
    timeframe: str = "1d"
    confidence: float = 0.0
    reason: str = ""
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)  # 시장 분석 컨텍스트

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_webhook_url() -> str | None:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        return data.get("webhook_url")
    return None


def load_webhook_urls() -> dict[str, str]:
    """Load all named webhook URLs from config.

    Returns dict like {"scalping": "https://...", "swing": "https://..."}.
    Falls back to {"default": webhook_url} if webhooks dict is absent.
    """
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        webhooks = data.get("webhooks")
        if isinstance(webhooks, dict):
            return {k: v for k, v in webhooks.items() if v}
        url = data.get("webhook_url")
        if url:
            return {"default": url}
    return {}


def load_webhook_url_for(channel: str) -> str | None:
    """Load webhook URL for a specific channel name (e.g. 'scalping', 'swing').

    Falls back to the default webhook_url if the channel is not found.
    """
    webhooks = load_webhook_urls()
    url = webhooks.get(channel)
    if url:
        return url
    # Fallback to default webhook_url
    return load_webhook_url()


def save_webhook_url(url: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
    else:
        data = {}
    data["webhook_url"] = url
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def save_webhook_urls(webhooks: dict[str, str]) -> None:
    """Save named webhook URLs to config, preserving other fields."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
    else:
        data = {}
    data["webhooks"] = webhooks
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def _build_embed(signal: Signal) -> dict[str, Any]:
    emoji = SIDE_EMOJI.get(signal.side, "\u26a0\ufe0f")
    color = STRATEGY_COLOR.get(signal.strategy, 0x607D8B)

    risk = abs(signal.entry - signal.stop_loss)
    risk_pct = (risk / signal.entry * 100) if signal.entry else 0

    rr_text = ""
    if risk > 0 and signal.take_profits:
        rrs = [f"{abs(tp - signal.entry) / risk:.1f}R" for tp in signal.take_profits]
        rr_text = f" ({' / '.join(rrs)})"

    if signal.take_profits:
        tp_parts = []
        for tp in signal.take_profits:
            tp_pct = abs(tp - signal.entry) / signal.entry * 100 if signal.entry else 0
            tp_parts.append(f"${tp:,.2f} (+{tp_pct:.1f}%)")
        tp_text = " / ".join(tp_parts)
    else:
        tp_text = "—"

    # Confidence bar
    filled = int(signal.confidence * 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    conf_text = f"{bar} {signal.confidence:.0%}"

    return {
        "embeds": [{
            "title": f"{emoji} {signal.side} {signal.symbol.replace('/USDT', '')}",
            "color": color,
            "fields": [
                {"name": "전략", "value": signal.strategy.replace("_", " "), "inline": True},
                {"name": "타임프레임", "value": signal.timeframe, "inline": True},
                {"name": "레버리지", "value": f"{signal.leverage}x", "inline": True},
                {"name": "진입가", "value": f"${signal.entry:,.4f}", "inline": True},
                {"name": "손절가", "value": f"${signal.stop_loss:,.4f} (-{risk_pct:.1f}%)", "inline": True},
                {"name": "목표가", "value": f"{tp_text}{rr_text}", "inline": True},
                {"name": "사유", "value": signal.reason or "—", "inline": False},
            ],
            "footer": {"text": f"신뢰도 {conf_text} | 트레일링 1.5% | {signal.timestamp}"},
        }],
    }


def send_signal(signal: Signal, webhook_url: str | None = None, channel: str | None = None) -> bool:
    url = webhook_url or (load_webhook_url_for(channel) if channel else None) or load_webhook_url()
    if not url:
        logger.warning("Discord webhook URL not configured")
        return False

    payload = _build_embed(signal)
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TradingBot/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.URLError as e:
        logger.error("Discord send failed: %s", e)
        return False


def send_position_alert(alert, webhook_url: str | None = None, channel: str | None = None) -> bool:
    """Send position management alert (TP/SL/TS) to Discord."""
    from engine.alerts.positions import Alert as PositionAlert  # noqa: F401

    url = webhook_url or (load_webhook_url_for(channel) if channel else None) or load_webhook_url()
    if not url:
        logger.warning("Discord webhook URL not configured")
        return False

    pos = alert.position
    pnl_pct = pos.pnl_pct * 100
    pnl_sign = "+" if pnl_pct >= 0 else ""
    symbol_short = pos.signal.symbol.replace("/USDT", "")

    # Duration calculation
    try:
        opened = datetime.fromisoformat(pos.opened_at.replace(" UTC", "+00:00"))
        now = datetime.now(timezone.utc)
        duration = now - opened
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        duration_text = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    except Exception:
        duration_text = "—"

    # Color and emoji based on alert type
    alert_config = {
        "TP1": {"emoji": "\U0001f4b0", "color": 0x4CAF50, "title": f"1차 익절 도달 — {symbol_short}"},
        "TP2": {"emoji": "\U0001f4b0\U0001f4b0", "color": 0xFFD700, "title": f"2차 익절 도달 — {symbol_short}"},
        "SL": {"emoji": "\U0001f6d1", "color": 0xF44336, "title": f"손절 도달 — {symbol_short}"},
        "TS": {"emoji": "\U0001f512", "color": 0xFF9800, "title": f"트레일링 스탑 발동 — {symbol_short}"},
        "CLOSE": {"emoji": "\u274c", "color": 0x607D8B, "title": f"포지션 종료 — {symbol_short}"},
    }

    cfg = alert_config.get(alert.type, {"emoji": "\u2139\ufe0f", "color": 0x607D8B, "title": f"알림 — {symbol_short}"})

    fields = [
        {"name": "진입가", "value": f"${pos.entry_price:,.4f}", "inline": True},
        {"name": "현재가", "value": f"${pos.current_price:,.4f} ({pnl_sign}{pnl_pct:.1f}%)", "inline": True},
        {"name": "손익", "value": f"{pnl_sign}{pnl_pct:.1f}%", "inline": True},
    ]

    if pos.trailing_stop is not None:
        fields.append({"name": "트레일링 스탑", "value": f"${pos.trailing_stop:,.4f}", "inline": True})

    fields.append({"name": "보유 시간", "value": duration_text, "inline": True})
    fields.append({"name": "메시지", "value": alert.message, "inline": False})

    payload = {
        "embeds": [{
            "title": f"{cfg['emoji']} {cfg['title']}",
            "color": cfg["color"],
            "fields": fields,
            "footer": {"text": f"{pos.signal.strategy} | {pos.signal.side} | {pos.signal.symbol}"},
        }]
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TradingBot/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.URLError as e:
        logger.error("Discord position alert failed: %s", e)
        return False


def send_text(message: str, webhook_url: str | None = None, channel: str | None = None) -> bool:
    url = webhook_url or (load_webhook_url_for(channel) if channel else None) or load_webhook_url()
    if not url:
        return False

    data = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TradingBot/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.URLError:
        return False

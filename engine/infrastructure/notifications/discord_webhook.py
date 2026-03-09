from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from engine.application.trading.charts import build_signal_chart
from engine.application.trading.presenters import build_signal_presentation
from engine.domain.trading.models import ExecutionRecord, PendingOrder, TradingSignal
from engine.domain.trading.ports import NotificationPort


class DiscordWebhookNotifier(NotificationPort):
    def __init__(self, config_path: str | Path = "config/discord.json") -> None:
        self.config_path = Path(config_path)

    def send_signal(self, signal: TradingSignal, mode_label: str) -> bool:
        presentation = build_signal_presentation(signal, mode_label)
        embed = {
            "title": presentation.title,
            "color": presentation.color,
            "fields": [
                {"name": field.name, "value": field.value, "inline": field.inline}
                for field in presentation.fields
            ],
            "footer": {"text": presentation.footer},
        }
        chart_data = build_signal_chart(signal)
        if chart_data:
            embed["image"] = {"url": "attachment://chart.png"}
        payload = {"embeds": [embed]}
        return self._post(payload, timeframe=signal.timeframe, chart_data=chart_data)

    def send_pending(self, pending: PendingOrder) -> bool:
        return self.send_text(
            f"Pending approval `{pending.pending_id}` for {pending.signal.symbol} "
            f"{pending.signal.side.value} {pending.signal.action.value} qty={pending.quantity}",
            timeframe=pending.signal.timeframe,
        )

    def send_execution(self, execution: ExecutionRecord) -> bool:
        return self.send_text(
            f"Execution `{execution.order_id}` {execution.symbol} {execution.action.value} "
            f"{execution.side.value} qty={execution.quantity} price={execution.price:,.4f}",
        )

    def send_text(self, message: str, timeframe: str | None = None) -> bool:
        return self._post({"content": message}, timeframe=timeframe)

    def _post(self, payload: dict, timeframe: str | None = None, chart_data: bytes | None = None) -> bool:
        url = self._load_webhook_url(timeframe=timeframe)
        if not url:
            return False
        try:
            if chart_data:
                req = urllib.request.Request(
                    url,
                    data=_multipart_body(payload, chart_data),
                    headers={
                        "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}",
                        "User-Agent": "stock-bot/2.0",
                    },
                    method="POST",
                )
            else:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "stock-bot/2.0"},
                    method="POST",
                )
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.status in (200, 204)
        except urllib.error.URLError:
            return False

    def _load_webhook_url(self, timeframe: str | None = None) -> str | None:
        env_url = os.getenv("DISCORD_WEBHOOK_URL")
        if env_url:
            return env_url
        if not self.config_path.exists():
            return None
        data = json.loads(self.config_path.read_text())
        if timeframe:
            key = f"tf_{timeframe}"
            webhook = data.get("webhooks", {}).get(key)
            if webhook:
                return webhook
        return data.get("webhook_url")


_BOUNDARY = "----stockbotboundary7MA4YWxkTrZu0gW"


def _multipart_body(payload: dict, chart_data: bytes) -> bytes:
    body = bytearray()
    body.extend(f"--{_BOUNDARY}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.extend(b"Content-Type: application/json\r\n\r\n")
    body.extend(json.dumps(payload).encode("utf-8"))
    body.extend(b"\r\n")
    body.extend(f"--{_BOUNDARY}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="files[0]"; filename="chart.png"\r\n')
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(chart_data)
    body.extend(b"\r\n")
    body.extend(f"--{_BOUNDARY}--\r\n".encode())
    return bytes(body)


class MemoryNotifier(NotificationPort):
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.signals: list[TradingSignal] = []
        self.pending: list[PendingOrder] = []
        self.executions: list[ExecutionRecord] = []

    def send_signal(self, signal: TradingSignal, mode_label: str) -> bool:
        self.signals.append(signal)
        self.messages.append(f"signal:{mode_label}:{signal.signal_id}:{signal.timeframe}")
        return True

    def send_pending(self, pending: PendingOrder) -> bool:
        self.pending.append(pending)
        self.messages.append(f"pending:{pending.pending_id}")
        return True

    def send_execution(self, execution: ExecutionRecord) -> bool:
        self.executions.append(execution)
        self.messages.append(f"execution:{execution.order_id}")
        return True

    def send_text(self, message: str) -> bool:
        self.messages.append(message)
        return True

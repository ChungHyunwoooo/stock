
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from engine.application.trading.charts import build_signal_chart
from engine.application.trading.presenters import build_signal_presentation
from engine.core.models import ExecutionRecord, PendingOrder, TradingSignal
from engine.core.ports import NotificationPort

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

    def send_performance_alert(self, snapshot: object) -> bool:
        """Send a performance degradation embed alert.

        *snapshot* is a ``PerformanceSnapshot`` (imported lazily to avoid
        circular imports).
        """
        level: str = getattr(snapshot, "alert_level", "none")
        if level == "none":
            return True

        sid = getattr(snapshot, "strategy_id", "unknown")
        rolling_sharpe = getattr(snapshot, "rolling_sharpe", None)
        baseline_sharpe = getattr(snapshot, "baseline_sharpe", None)
        deg_sharpe = getattr(snapshot, "degradation_pct_sharpe", None)
        rolling_wr = getattr(snapshot, "rolling_win_rate", None)
        baseline_wr = getattr(snapshot, "baseline_win_rate", None)
        deg_wr = getattr(snapshot, "degradation_pct_win_rate", None)

        if level == "critical":
            color = 0xFF0000
            title = f"[CRITICAL] {sid} 성과 저하 - 진입 일시정지"
        else:
            color = 0xFFA500
            title = f"[WARNING] {sid} 성과 저하"

        def _fmt(val: float | None, pct: bool = False) -> str:
            if val is None:
                return "N/A"
            return f"{val:.1%}" if pct else f"{val:.4f}"

        fields = [
            {"name": "현재 Sharpe", "value": _fmt(rolling_sharpe), "inline": True},
            {"name": "기준 Sharpe", "value": _fmt(baseline_sharpe), "inline": True},
            {"name": "Sharpe 저하율", "value": _fmt(deg_sharpe, pct=True), "inline": True},
            {"name": "현재 승률 (Win Rate)", "value": _fmt(rolling_wr, pct=True), "inline": True},
            {"name": "기준 승률", "value": _fmt(baseline_wr, pct=True), "inline": True},
            {"name": "승률 저하율", "value": _fmt(deg_wr, pct=True), "inline": True},
            {"name": "Alert Level", "value": level.upper(), "inline": True},
        ]

        from datetime import datetime, timezone

        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {"text": f"StrategyPerformanceMonitor | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"},
        }
        payload = {"embeds": [embed]}
        return self._post(payload)

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

    def send_performance_alert(self, snapshot: object) -> bool:
        level: str = getattr(snapshot, "alert_level", "none")
        if level == "none":
            return True
        sid = getattr(snapshot, "strategy_id", "unknown")
        self.messages.append(f"perf_alert:{level}:{sid}")
        return True

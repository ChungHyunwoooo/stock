
from __future__ import annotations

import json
from pathlib import Path

class DiscordUserPreferenceStore:
    def __init__(self, path: str | Path = 'state/discord_user_prefs.json') -> None:
        self.path = Path(path)

    def get_recent_exchange(self, user_id: int | str) -> str | None:
        data = self._load()
        prefs = data.get(str(user_id), {})
        exchange = prefs.get('recent_exchange')
        return exchange if isinstance(exchange, str) and exchange else None

    def set_recent_exchange(self, user_id: int | str, exchange: str) -> None:
        data = self._load()
        user_key = str(user_id)
        prefs = data.setdefault(user_key, {})
        prefs['recent_exchange'] = exchange
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

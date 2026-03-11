"""Strategy lifecycle state machine -- enforces legal state transitions."""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from engine.schema import StrategyStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when a disallowed state transition is attempted."""


class StrategyNotFoundError(Exception):
    """Raised when a strategy ID is not found in the registry."""


# ---------------------------------------------------------------------------
# Transition map
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[StrategyStatus, set[StrategyStatus]] = {
    StrategyStatus.draft: {StrategyStatus.testing},
    StrategyStatus.testing: {StrategyStatus.draft, StrategyStatus.paper},
    StrategyStatus.paper: {StrategyStatus.active},
    StrategyStatus.active: {StrategyStatus.paper, StrategyStatus.archived},
    StrategyStatus.archived: {StrategyStatus.draft},
}

# ---------------------------------------------------------------------------
# LifecycleManager
# ---------------------------------------------------------------------------


class LifecycleManager:
    """Pure domain service that manages strategy lifecycle via registry.json.

    Responsibilities:
    - Enforce FSM transition rules (ALLOWED_TRANSITIONS)
    - Record transition history (status_history)
    - Atomic registry.json writes (tempfile + rename)
    - Register / query strategies
    - Fire transition callbacks (observer pattern)

    Does NOT call Discord, API, or any external service directly.
    Callbacks allow external listeners (e.g. EventNotifier) to react.
    """

    def __init__(self, registry_path: str | Path = "strategies/registry.json") -> None:
        self.registry_path = Path(registry_path)
        self._on_transition_callbacks: list[Callable[[str, str, str], None]] = []

    def add_transition_listener(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a callback invoked after successful transitions.

        Callback signature: (strategy_id, from_status, to_status) -> None
        """
        self._on_transition_callbacks.append(callback)

    # -- public API ----------------------------------------------------------

    def transition(
        self,
        strategy_id: str,
        target: str,
        reason: str = "",
        gate: "PromotionGate | None" = None,
        gate_config: "PromotionConfig | None" = None,
        session: "Session | None" = None,
    ) -> dict:
        """Transition a strategy to *target* status, recording history.

        For paper->active transitions, *gate* is required. The gate evaluates
        promotion criteria and blocks the transition if criteria are not met.

        Raises InvalidTransitionError for disallowed transitions.
        Raises StrategyNotFoundError if *strategy_id* is absent.
        """
        target_status = StrategyStatus(target)
        registry = self._load()
        entry = self._find_entry(registry, strategy_id)

        current_value = entry["status"]
        # If current status is not in ALLOWED_TRANSITIONS (e.g. deprecated),
        # any transition is invalid.
        try:
            current_status = StrategyStatus(current_value)
        except ValueError:
            raise InvalidTransitionError(
                f"{strategy_id}: {current_value} -> {target_status.value} "
                f"전이 불가 (현재 상태 '{current_value}'는 관리 대상 아님)"
            )

        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise InvalidTransitionError(
                f"{strategy_id}: {current_status.value} -> {target_status.value} 전이 불가"
            )

        # paper->active: enforce promotion gate
        if current_status == StrategyStatus.paper and target_status == StrategyStatus.active:
            if gate is None:
                raise InvalidTransitionError(
                    "paper->active 전이에는 PromotionGate가 필요합니다"
                )
            if gate_config is None or session is None:
                raise InvalidTransitionError(
                    "paper->active 전이에는 gate_config와 session이 필요합니다"
                )
            result = gate.evaluate(strategy_id, gate_config, session)
            if not result.passed:
                raise InvalidTransitionError(f"승격 기준 미충족: {result.summary}")

        entry["status"] = target_status.value
        history = entry.setdefault("status_history", [])
        history.append({
            "from": current_status.value,
            "to": target_status.value,
            "date": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        })

        self._save(registry)
        logger.info(
            "%s: %s -> %s (%s)", strategy_id, current_status.value, target_status.value, reason
        )

        for cb in self._on_transition_callbacks:
            try:
                cb(strategy_id, current_status.value, target_status.value)
            except Exception:
                logger.warning("Transition callback failed for %s", strategy_id, exc_info=True)

        return entry

    def register(self, entry: dict) -> dict:
        """Register a new strategy as draft with initial status_history.

        *entry* must contain at least ``id`` and ``name``.
        ``status`` is forced to ``draft`` regardless of input.
        """
        registry = self._load()

        # Force draft status
        entry["status"] = StrategyStatus.draft.value
        entry["status_history"] = [
            {
                "from": None,
                "to": StrategyStatus.draft.value,
                "date": datetime.now(timezone.utc).isoformat(),
                "reason": "initial registration",
            }
        ]

        registry["strategies"].append(entry)
        self._save(registry)
        logger.info("Registered strategy: %s", entry.get("id"))
        return entry

    def get_strategy(self, strategy_id: str) -> dict:
        """Return a strategy entry by id, or raise StrategyNotFoundError."""
        registry = self._load()
        return self._find_entry(registry, strategy_id)

    def list_by_status(self, status: str | None = None) -> list[dict]:
        """Return strategies filtered by *status*. None returns all."""
        registry = self._load()
        strategies = registry.get("strategies", [])
        if status is None:
            return list(strategies)
        return [s for s in strategies if s.get("status") == status]

    # -- internals -----------------------------------------------------------

    def _load(self) -> dict:
        """Read registry.json and return parsed dict."""
        text = self.registry_path.read_text(encoding="utf-8")
        return json.loads(text)

    def _save(self, data: dict) -> None:
        """Write registry.json atomically via tempfile + rename."""
        content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.registry_path.parent, suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp).replace(self.registry_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _find_entry(registry: dict, strategy_id: str) -> dict:
        """Find strategy by id in registry dict. Raises StrategyNotFoundError."""
        for entry in registry.get("strategies", []):
            if entry.get("id") == strategy_id:
                return entry
        raise StrategyNotFoundError(f"Strategy not found: {strategy_id}")

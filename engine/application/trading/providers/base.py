
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from engine.schema import StrategyDefinition

class StrategySourcePort(Protocol):
    def load(self, path: str | Path) -> StrategyDefinition:
        ...

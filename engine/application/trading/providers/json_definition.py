
from __future__ import annotations

import json
from pathlib import Path

from engine.schema import StrategyDefinition

class JsonStrategySource:
    def load(self, path: str | Path) -> StrategyDefinition:
        strategy_path = Path(path)
        return StrategyDefinition.model_validate(json.loads(strategy_path.read_text()))

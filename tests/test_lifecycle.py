"""Tests for engine/strategy/lifecycle_manager.py -- LifecycleManager FSM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.schema import StrategyDefinition, StrategyStatus
from engine.strategy.lifecycle_manager import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    LifecycleManager,
    StrategyNotFoundError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_path(tmp_path):
    """Create a temporary registry.json with sample strategies."""
    registry = {
        "strategies": [
            {
                "id": "test_rsi",
                "name": "Test RSI",
                "status": "draft",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "definition": "strategies/test_rsi/definition.json",
            },
            {
                "id": "test_macd",
                "name": "Test MACD",
                "status": "testing",
                "direction": ["LONG", "SHORT"],
                "timeframe": ["4h"],
                "regime": ["BULL"],
                "definition": "strategies/test_macd/definition.json",
            },
            {
                "id": "test_active",
                "name": "Test Active",
                "status": "active",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "definition": "strategies/test_active/definition.json",
            },
            {
                "id": "test_archived",
                "name": "Test Archived",
                "status": "archived",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "definition": "strategies/test_archived/definition.json",
            },
            {
                "id": "test_paper",
                "name": "Test Paper",
                "status": "paper",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "definition": "strategies/test_paper/definition.json",
            },
            {
                "id": "test_deprecated",
                "name": "Test Deprecated",
                "status": "deprecated",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "deprecated_reason": "old strategy",
                "definition": "strategies/test_deprecated/definition.json",
            },
        ]
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def manager(registry_path):
    """LifecycleManager with temporary registry."""
    return LifecycleManager(registry_path=registry_path)


# ---------------------------------------------------------------------------
# Forward transitions
# ---------------------------------------------------------------------------

def test_forward_transitions(manager, registry_path):
    """draft->testing, testing->paper, paper->active, active->archived succeed."""
    # draft -> testing
    result = manager.transition("test_rsi", "testing", reason="start testing")
    assert result["status"] == "testing"

    # testing -> paper
    result = manager.transition("test_macd", "paper", reason="passed backtest")
    assert result["status"] == "paper"

    # paper -> active
    result = manager.transition("test_paper", "active", reason="paper trading passed")
    assert result["status"] == "active"

    # active -> archived
    result = manager.transition("test_active", "archived", reason="retired")
    assert result["status"] == "archived"

    # Verify persistence
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    statuses = {s["id"]: s["status"] for s in data["strategies"]}
    assert statuses["test_rsi"] == "testing"
    assert statuses["test_macd"] == "paper"
    assert statuses["test_paper"] == "active"
    assert statuses["test_active"] == "archived"


# ---------------------------------------------------------------------------
# Allowed reverse transitions
# ---------------------------------------------------------------------------

def test_allowed_reverse_transitions(manager):
    """active->paper, testing->draft, archived->draft succeed."""
    # active -> paper
    result = manager.transition("test_active", "paper", reason="demote")
    assert result["status"] == "paper"

    # testing -> draft
    result = manager.transition("test_macd", "draft", reason="revert")
    assert result["status"] == "draft"

    # archived -> draft
    result = manager.transition("test_archived", "draft", reason="reactivate")
    assert result["status"] == "draft"


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

def test_invalid_transitions(manager):
    """Disallowed transitions raise InvalidTransitionError."""
    invalid_pairs = [
        ("test_rsi", "active"),       # draft -> active
        ("test_rsi", "paper"),        # draft -> paper
        ("test_rsi", "archived"),     # draft -> archived
        ("test_paper", "testing"),    # paper -> testing
        ("test_paper", "draft"),      # paper -> draft
        ("test_archived", "active"),  # archived -> active
        ("test_archived", "testing"), # archived -> testing
        ("test_active", "draft"),     # active -> draft
        ("test_active", "testing"),   # active -> testing
    ]
    for strategy_id, target in invalid_pairs:
        with pytest.raises(InvalidTransitionError):
            manager.transition(strategy_id, target)


# ---------------------------------------------------------------------------
# Transition history
# ---------------------------------------------------------------------------

def test_transition_history(manager):
    """Transition appends {from, to, date, reason} to status_history."""
    result = manager.transition("test_rsi", "testing", reason="begin test")
    history = result["status_history"]
    assert len(history) == 1

    record = history[-1]
    assert record["from"] == "draft"
    assert record["to"] == "testing"
    assert "date" in record
    # ISO format check
    assert "T" in record["date"]
    assert record["reason"] == "begin test"

    # Second transition adds another record
    result = manager.transition("test_rsi", "paper", reason="promote")
    assert len(result["status_history"]) == 2
    assert result["status_history"][-1]["from"] == "testing"
    assert result["status_history"][-1]["to"] == "paper"


# ---------------------------------------------------------------------------
# Strategy not found
# ---------------------------------------------------------------------------

def test_strategy_not_found(manager):
    """Non-existent strategy_id raises StrategyNotFoundError."""
    with pytest.raises(StrategyNotFoundError):
        manager.transition("nonexistent_id", "testing")


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def test_atomic_write(tmp_path):
    """If write fails mid-way, original registry.json is preserved."""
    registry = {
        "strategies": [
            {
                "id": "safe_strategy",
                "name": "Safe",
                "status": "draft",
                "direction": ["LONG"],
                "timeframe": ["1h"],
                "regime": ["ALL"],
                "definition": "strategies/safe/definition.json",
            }
        ]
    }
    path = tmp_path / "registry.json"
    original_content = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    path.write_text(original_content, encoding="utf-8")

    mgr = LifecycleManager(registry_path=path)

    # Monkey-patch _save to simulate failure after load but during save
    original_save = mgr._save

    def failing_save(data):
        # Write partial content to simulate crash (but use atomic pattern)
        raise OSError("Simulated disk failure")

    mgr._save = failing_save

    with pytest.raises(OSError):
        mgr.transition("safe_strategy", "testing", reason="will fail")

    # Original file must be intact
    assert path.read_text(encoding="utf-8") == original_content
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["strategies"][0]["status"] == "draft"


# ---------------------------------------------------------------------------
# Register strategy
# ---------------------------------------------------------------------------

def test_register_strategy(manager, registry_path):
    """register() adds a new strategy as draft with initial status_history."""
    new_entry = {
        "id": "new_strat",
        "name": "New Strategy",
        "direction": ["LONG"],
        "timeframe": ["1h"],
        "regime": ["ALL"],
        "definition": "strategies/new_strat/definition.json",
    }
    result = manager.register(new_entry)

    assert result["status"] == "draft"
    assert len(result["status_history"]) == 1
    assert result["status_history"][0]["from"] is None
    assert result["status_history"][0]["to"] == "draft"

    # Verify persisted
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["strategies"]]
    assert "new_strat" in ids


# ---------------------------------------------------------------------------
# Get strategy
# ---------------------------------------------------------------------------

def test_get_strategy(manager):
    """get_strategy returns dict for existing id, raises for missing."""
    entry = manager.get_strategy("test_rsi")
    assert entry["id"] == "test_rsi"
    assert entry["name"] == "Test RSI"

    with pytest.raises(StrategyNotFoundError):
        manager.get_strategy("does_not_exist")


# ---------------------------------------------------------------------------
# List by status
# ---------------------------------------------------------------------------

def test_list_by_status(manager):
    """list_by_status filters strategies by status value."""
    drafts = manager.list_by_status("draft")
    assert all(s["status"] == "draft" for s in drafts)
    assert any(s["id"] == "test_rsi" for s in drafts)

    actives = manager.list_by_status("active")
    assert all(s["status"] == "active" for s in actives)
    assert any(s["id"] == "test_active" for s in actives)

    # None returns all
    all_strats = manager.list_by_status(None)
    assert len(all_strats) == 6


# ---------------------------------------------------------------------------
# Deprecated strategies ignored
# ---------------------------------------------------------------------------

def test_deprecated_strategies_ignored(manager):
    """deprecated status has no ALLOWED_TRANSITIONS key, so transition fails."""
    with pytest.raises(InvalidTransitionError):
        manager.transition("test_deprecated", "draft")

    with pytest.raises(InvalidTransitionError):
        manager.transition("test_deprecated", "archived")


# ---------------------------------------------------------------------------
# Reference strategy validation
# ---------------------------------------------------------------------------

def test_reference_strategy_valid():
    """ref_rsi_divergence/definition.json validates against StrategyDefinition schema."""
    definition_path = Path("strategies/ref_rsi_divergence/definition.json")
    assert definition_path.exists(), f"{definition_path} not found"

    data = json.loads(definition_path.read_text(encoding="utf-8"))
    strategy = StrategyDefinition.model_validate(data)

    assert strategy.name == "RSI Divergence"
    assert strategy.version == "1.0"
    assert strategy.status.value == "draft"
    assert strategy.direction.value == "both"
    assert len(strategy.indicators) == 2
    assert strategy.indicators[0].name == "RSI"
    assert strategy.indicators[1].name == "ATR"

    # research.md must exist and have required sections
    research_path = Path("strategies/ref_rsi_divergence/research.md")
    assert research_path.exists(), f"{research_path} not found"
    content = research_path.read_text(encoding="utf-8")
    assert "## 출처" in content
    assert "## 전략 로직 요약" in content
    assert "## 백테스트 결과 요약" in content

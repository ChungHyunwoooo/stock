"""Tests for Discord lifecycle command plugin -- autocomplete, embed, confirm view."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    """Temporary registry.json for autocomplete tests."""
    registry = {
        "strategies": [
            {"id": "strat_a", "name": "Alpha Strategy", "status": "draft"},
            {"id": "strat_b", "name": "Beta Strategy", "status": "testing"},
            {"id": "strat_c", "name": "Gamma Strategy", "status": "active"},
        ]
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def manager(registry_path):
    return LifecycleManager(registry_path=registry_path)


def _make_interaction(namespace_attrs: dict | None = None):
    """Create a mock Interaction with namespace attributes."""
    interaction = AsyncMock()
    ns = MagicMock()
    for k, v in (namespace_attrs or {}).items():
        setattr(ns, k, v)
    interaction.namespace = ns
    return interaction


# ---------------------------------------------------------------------------
# strategy_autocomplete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strategy_autocomplete(manager):
    """strategy_autocomplete returns all strategies as Choice(name, value)."""
    from engine.interfaces.discord.autocomplete import strategy_autocomplete

    interaction = _make_interaction()
    choices = await strategy_autocomplete(interaction, "", _manager=manager)

    assert len(choices) == 3
    values = [c.value for c in choices]
    assert "strat_a" in values
    assert "strat_b" in values
    assert "strat_c" in values
    # name format: "{name} ({id})"
    names = [c.name for c in choices]
    assert any("Alpha Strategy" in n and "strat_a" in n for n in names)


@pytest.mark.asyncio
async def test_strategy_autocomplete_filter(manager):
    """strategy_autocomplete filters by current input."""
    from engine.interfaces.discord.autocomplete import strategy_autocomplete

    interaction = _make_interaction()
    choices = await strategy_autocomplete(interaction, "alpha", _manager=manager)

    assert len(choices) == 1
    assert choices[0].value == "strat_a"


# ---------------------------------------------------------------------------
# target_status_autocomplete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_target_status_autocomplete_draft(manager):
    """For draft strategy, target_status_autocomplete returns [testing]."""
    from engine.interfaces.discord.autocomplete import target_status_autocomplete

    interaction = _make_interaction({"strategy_id": "strat_a"})
    choices = await target_status_autocomplete(interaction, "", _manager=manager)

    values = [c.value for c in choices]
    assert values == ["testing"]


@pytest.mark.asyncio
async def test_target_status_autocomplete_active(manager):
    """For active strategy, target_status_autocomplete returns [paper, archived]."""
    from engine.interfaces.discord.autocomplete import target_status_autocomplete

    interaction = _make_interaction({"strategy_id": "strat_c"})
    choices = await target_status_autocomplete(interaction, "", _manager=manager)

    values = sorted(c.value for c in choices)
    assert values == ["archived", "paper"]


# ---------------------------------------------------------------------------
# LifecycleCommandPlugin
# ---------------------------------------------------------------------------

def test_lifecycle_plugin_registered():
    """LifecycleCommandPlugin is in DEFAULT_COMMAND_PLUGINS."""
    from engine.interfaces.discord.commands import DEFAULT_COMMAND_PLUGINS

    names = [p.name for p in DEFAULT_COMMAND_PLUGINS]
    assert "lifecycle" in names


def test_lifecycle_plugin_name():
    """LifecycleCommandPlugin.name is 'lifecycle'."""
    from engine.interfaces.discord.commands.lifecycle import LifecycleCommandPlugin

    plugin = LifecycleCommandPlugin()
    assert plugin.name == "lifecycle"


# ---------------------------------------------------------------------------
# TransitionConfirmView
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_confirm_view(manager, registry_path):
    """Confirm button calls manager.transition() and edits message with embed."""
    from engine.interfaces.discord.commands.lifecycle import TransitionConfirmView

    ctx = MagicMock()
    ctx.lifecycle_manager = manager

    view = TransitionConfirmView(
        strategy_id="strat_a",
        from_status="draft",
        to_status="testing",
        context=ctx,
    )

    interaction = AsyncMock()

    # discord.ui.button callback wraps (self, interaction, button) -> __call__(interaction)
    await view.confirm.callback(interaction)

    interaction.response.edit_message.assert_called_once()
    call_kwargs = interaction.response.edit_message.call_args
    assert call_kwargs.kwargs.get("view") is None

    # Verify transition happened
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    strat = next(s for s in data["strategies"] if s["id"] == "strat_a")
    assert strat["status"] == "testing"


@pytest.mark.asyncio
async def test_transition_invalid_shows_error(manager):
    """InvalidTransitionError shows error embed."""
    from engine.interfaces.discord.commands.lifecycle import TransitionConfirmView

    ctx = MagicMock()
    ctx.lifecycle_manager = manager

    # draft -> active is invalid
    view = TransitionConfirmView(
        strategy_id="strat_a",
        from_status="draft",
        to_status="active",
        context=ctx,
    )

    interaction = AsyncMock()
    await view.confirm.callback(interaction)

    interaction.response.edit_message.assert_called_once()
    call_kwargs = interaction.response.edit_message.call_args
    assert call_kwargs.kwargs.get("view") is None


# ---------------------------------------------------------------------------
# build_transition_embed
# ---------------------------------------------------------------------------

def test_build_transition_embed():
    """Embed contains strategy name, status change, and history count."""
    from engine.interfaces.discord.commands.lifecycle import build_transition_embed

    embed = build_transition_embed(
        strategy_name="Alpha Strategy",
        strategy_id="strat_a",
        from_status="draft",
        to_status="testing",
        history=[
            {"from": "draft", "to": "testing", "date": "2026-03-11T00:00:00", "reason": "test"},
        ],
    )

    assert "전략 전이" in embed.title
    field_names = [f.name for f in embed.fields]
    assert "전략" in field_names
    assert "상태 변경" in field_names
    assert "전이 이력" in field_names
    # Verify content
    strat_field = next(f for f in embed.fields if f.name == "전략")
    assert "Alpha Strategy" in strat_field.value
    assert "strat_a" in strat_field.value

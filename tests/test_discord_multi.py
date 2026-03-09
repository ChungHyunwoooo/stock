"""Tests for Discord multi-webhook support."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def tmp_discord_config(tmp_path):
    """Create a temporary discord.json config file."""
    config_path = tmp_path / "discord.json"
    config_path.write_text(json.dumps({
        "webhook_url": "https://discord.com/api/webhooks/default/token",
        "webhooks": {
            "scalping": "https://discord.com/api/webhooks/scalping/token",
            "swing": "https://discord.com/api/webhooks/swing/token",
        }
    }))
    return config_path


@pytest.fixture
def tmp_discord_config_legacy(tmp_path):
    """Create a legacy discord.json without webhooks dict."""
    config_path = tmp_path / "discord.json"
    config_path.write_text(json.dumps({
        "webhook_url": "https://discord.com/api/webhooks/legacy/token",
    }))
    return config_path


class TestLoadWebhookUrls:
    def test_load_all_webhooks(self, tmp_discord_config):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config):
            from engine.alerts.discord import load_webhook_urls
            urls = load_webhook_urls()
            assert "scalping" in urls
            assert "swing" in urls
            assert urls["scalping"] == "https://discord.com/api/webhooks/scalping/token"
            assert urls["swing"] == "https://discord.com/api/webhooks/swing/token"

    def test_load_fallback_to_default(self, tmp_discord_config_legacy):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config_legacy):
            from engine.alerts.discord import load_webhook_urls
            urls = load_webhook_urls()
            assert "default" in urls
            assert urls["default"] == "https://discord.com/api/webhooks/legacy/token"

    def test_load_empty_when_no_config(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        with patch("engine.alerts.discord.CONFIG_PATH", config_path):
            from engine.alerts.discord import load_webhook_urls
            urls = load_webhook_urls()
            assert urls == {}

    def test_load_skips_empty_urls(self, tmp_path):
        config_path = tmp_path / "discord.json"
        config_path.write_text(json.dumps({
            "webhook_url": "https://example.com",
            "webhooks": {
                "scalping": "https://example.com/scalping",
                "swing": "",  # empty
            }
        }))
        with patch("engine.alerts.discord.CONFIG_PATH", config_path):
            from engine.alerts.discord import load_webhook_urls
            urls = load_webhook_urls()
            assert "scalping" in urls
            assert "swing" not in urls


class TestLoadWebhookUrlFor:
    def test_load_specific_channel(self, tmp_discord_config):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config):
            from engine.alerts.discord import load_webhook_url_for
            url = load_webhook_url_for("swing")
            assert url == "https://discord.com/api/webhooks/swing/token"

    def test_fallback_to_default(self, tmp_discord_config):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config):
            from engine.alerts.discord import load_webhook_url_for
            url = load_webhook_url_for("nonexistent")
            assert url == "https://discord.com/api/webhooks/default/token"

    def test_legacy_fallback(self, tmp_discord_config_legacy):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config_legacy):
            from engine.alerts.discord import load_webhook_url_for
            url = load_webhook_url_for("swing")
            assert url == "https://discord.com/api/webhooks/legacy/token"


class TestSaveWebhookUrls:
    def test_save_webhooks(self, tmp_path):
        config_path = tmp_path / "discord.json"
        config_path.write_text(json.dumps({"webhook_url": "https://original.com"}))
        with patch("engine.alerts.discord.CONFIG_PATH", config_path):
            from engine.alerts.discord import save_webhook_urls
            save_webhook_urls({"scalping": "https://s.com", "swing": "https://sw.com"})
            data = json.loads(config_path.read_text())
            assert data["webhook_url"] == "https://original.com"  # preserved
            assert data["webhooks"]["scalping"] == "https://s.com"
            assert data["webhooks"]["swing"] == "https://sw.com"

    def test_save_creates_file(self, tmp_path):
        config_path = tmp_path / "subdir" / "discord.json"
        with patch("engine.alerts.discord.CONFIG_PATH", config_path):
            from engine.alerts.discord import save_webhook_urls
            save_webhook_urls({"swing": "https://sw.com"})
            assert config_path.exists()
            data = json.loads(config_path.read_text())
            assert data["webhooks"]["swing"] == "https://sw.com"


class TestSaveWebhookUrl:
    def test_save_preserves_webhooks(self, tmp_discord_config):
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config):
            from engine.alerts.discord import save_webhook_url
            save_webhook_url("https://new-default.com")
            data = json.loads(tmp_discord_config.read_text())
            assert data["webhook_url"] == "https://new-default.com"
            assert "webhooks" in data  # preserved


class TestSendWithChannel:
    def test_send_signal_with_channel(self, tmp_discord_config):
        """send_signal should use channel-specific URL when channel is provided."""
        from engine.alerts.discord import Signal

        sig = Signal(
            strategy="TEST", symbol="BTC/USDT", side="LONG",
            entry=50000.0, stop_loss=49000.0, take_profits=[51000.0, 52000.0, 53000.0],
        )

        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config), \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 204
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            from engine.alerts.discord import send_signal
            result = send_signal(sig, channel="swing")
            assert result is True

            # Verify the swing webhook URL was used
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.full_url == "https://discord.com/api/webhooks/swing/token"

    def test_send_text_with_channel(self, tmp_discord_config):
        """send_text should use channel-specific URL."""
        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config), \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 204
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            from engine.alerts.discord import send_text
            result = send_text("test message", channel="scalping")
            assert result is True

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.full_url == "https://discord.com/api/webhooks/scalping/token"

    def test_send_without_channel_uses_default(self, tmp_discord_config):
        """Without channel param, should use default webhook_url."""
        from engine.alerts.discord import Signal

        sig = Signal(
            strategy="TEST", symbol="BTC/USDT", side="LONG",
            entry=50000.0, stop_loss=49000.0, take_profits=[51000.0],
        )

        with patch("engine.alerts.discord.CONFIG_PATH", tmp_discord_config), \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 204
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            from engine.alerts.discord import send_signal
            result = send_signal(sig)
            assert result is True

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.full_url == "https://discord.com/api/webhooks/default/token"

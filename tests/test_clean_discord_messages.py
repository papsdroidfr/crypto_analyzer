import json
from unittest.mock import MagicMock

import pytest

from scripts import clean_discord_messages


def test_main_cleans_messages_for_all_configured_webhooks(tmp_path, monkeypatch):
    config = {
        "discord": {
            "webhook_urls": {
                "daily": "https://discord.com/api/webhooks/123/daily-token",
                "hourly": "https://discord.com/api/webhooks/456/hourly-token",
                "weekly": "https://discord.com/api/webhooks/789/weekly-token",
            },
            "channel_ids": {
                "daily": "111",
                "hourly": "222",
                "weekly": "333",
            },
            "bot_token": "bot-token",
        }
    }
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    calls = []
    session = MagicMock()

    def fake_clean_messages(*args, **kwargs):
        calls.append((args[1], args[2], kwargs["dry_run"]))
        return 2, 0

    monkeypatch.setattr(clean_discord_messages.requests, "Session", lambda: session)
    monkeypatch.setattr(clean_discord_messages, "clean_messages", fake_clean_messages)
    monkeypatch.setattr(
        "sys.argv",
        ["clean_discord_messages.py", "--config", str(config_path), "--dry-run"],
    )

    clean_discord_messages.main()

    assert calls == [
        ("111", "123", True),
        ("222", "456", True),
        ("333", "789", True),
    ]


def test_main_requires_webhook_urls(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps({
            "discord": {
                "webhook_url": "https://discord.com/api/webhooks/123/legacy",
                "bot_token": "bot-token",
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["clean_discord_messages.py", "--config", str(config_path)]
    )

    with pytest.raises(SystemExit) as exc_info:
        clean_discord_messages.main()

    assert exc_info.value.code == 2

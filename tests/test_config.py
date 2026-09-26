from pathlib import Path

import pytest

from repo_agent_bot.config import Settings


def test_settings_require_telegram_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        Settings.from_env()


def test_settings_parse_allowlists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "not-a-real-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "123, 456")
    monkeypatch.setenv("GITHUB_REPOSITORY_ALLOWLIST", "Acme, Org/Repo")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SANDBOX_HOST_DATA_DIR", str(tmp_path / "host-data"))
    settings = Settings.from_env()
    assert settings.telegram_allowed_users == frozenset({123, 456})
    assert settings.github_repository_allowlist == ("acme", "org/repo")
    assert settings.sandbox_host_data_dir == (tmp_path / "host-data").resolve()
    assert settings.sandbox_network == "none"

from pathlib import Path

import pytest

from repo_agent_bot.sandbox import CommandSandbox


@pytest.mark.asyncio
async def test_local_sandbox_does_not_inherit_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "repository"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-leak")
    monkeypatch.setenv("AI_API_KEY", "must-not-leak-either")
    sandbox = CommandSandbox(
        mode="local",
        workspace=workspace,
        image="unused",
        memory="1g",
        cpus="1",
        network="none",
        command_timeout=10,
    )

    async with sandbox:
        result = await sandbox.run('printf \'%s|%s\' "$GITHUB_TOKEN" "$AI_API_KEY"')

    assert result.returncode == 0
    assert result.stdout == "|"

import subprocess
from pathlib import Path

import pytest

from repo_agent_bot.models import AgentResult, GitHubRepository
from repo_agent_bot.repository import RepositoryClient


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


@pytest.mark.asyncio
async def test_publish_creates_commit_and_patch_without_token(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("before\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "initial")
    git(root, "remote", "add", "origin", "https://github.com/acme/example.git")
    git(root, "checkout", "-b", "agent/telegram-test")
    (root / "README.md").write_text("after\n", encoding="utf-8")

    client = RepositoryClient(github_token="", command_timeout=30)
    publication = await client.publish(
        root=root,
        repository=GitHubRepository("acme", "example"),
        base_branch="main",
        branch="agent/telegram-test",
        task_id="abc123",
        prompt="Update readme",
        result=AgentResult(summary="Updated", tests="Not run"),
        create_pr=False,
    )

    assert publication.branch == "agent/telegram-test"
    assert publication.commit_sha == git(root, "rev-parse", "HEAD")
    assert publication.patch_path is not None
    assert publication.patch_path.is_file()
    assert "Subject: [PATCH] agent: Update readme" in publication.patch_path.read_text()
    assert git(root, "status", "--porcelain") == ""

from pathlib import Path

import pytest

from repo_agent_bot.database import Database
from repo_agent_bot.models import GitHubRepository


@pytest.mark.asyncio
async def test_repository_change_resets_conversation(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "bot.db"))
    await database.initialize()
    await database.set_repository(1, 10, GitHubRepository("one", "repo"))
    await database.add_conversation_message(1, "user", "first")

    await database.set_repository(1, 10, GitHubRepository("one", "repo"))
    assert await database.conversation_context(1) == [("user", "first")]

    await database.set_repository(1, 10, GitHubRepository("two", "repo"))
    assert await database.conversation_context(1) == []


@pytest.mark.asyncio
async def test_clear_repository_clears_context(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "bot.db"))
    await database.initialize()
    await database.set_repository(1, 10, GitHubRepository("one", "repo"))
    await database.add_conversation_message(1, "assistant", "answer")
    await database.clear_repository(1)

    assert await database.get_repository(1) is None
    assert await database.conversation_context(1) == []

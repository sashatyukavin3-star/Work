from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from .models import GitHubRepository, TaskRecord, TaskStatus


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    chat_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary TEXT,
                    error TEXT,
                    branch TEXT,
                    pull_request_url TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_chat_created
                    ON tasks(chat_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS conversation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_chat_id
                    ON conversation(chat_id, id DESC);
                """
            )
            await db.execute(
                "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE status IN (?, ?)",
                (
                    TaskStatus.FAILED,
                    "Bot restarted while the task was active",
                    _now(),
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                ),
            )
            await db.commit()

    async def set_repository(
        self, chat_id: int, user_id: int, repository: GitHubRepository
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT repository FROM sessions WHERE chat_id = ?", (chat_id,)
            )
            existing = await cursor.fetchone()
            await db.execute(
                """
                INSERT INTO sessions(chat_id, user_id, repository, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    repository = excluded.repository,
                    updated_at = excluded.updated_at
                """,
                (chat_id, user_id, repository.slug, _now()),
            )
            if existing and existing[0].lower() != repository.slug.lower():
                await db.execute("DELETE FROM conversation WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def get_repository(self, chat_id: int) -> GitHubRepository | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT repository FROM sessions WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
        if not row:
            return None
        owner, name = row[0].split("/", 1)
        return GitHubRepository(owner=owner, name=name)

    async def clear_repository(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM conversation WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def add_conversation_message(self, chat_id: int, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Conversation role must be user or assistant")
        # Keep the context useful without allowing the database to grow from huge pasted files.
        content = content.strip()[:12_000]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO conversation(chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, role, content, _now()),
            )
            await db.execute(
                """
                DELETE FROM conversation
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM conversation WHERE chat_id = ? ORDER BY id DESC LIMIT 20
                )
                """,
                (chat_id, chat_id),
            )
            await db.commit()

    async def conversation_context(self, chat_id: int, *, limit: int = 8) -> list[tuple[str, str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM conversation
                    WHERE chat_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (chat_id, limit),
            )
            rows = await cursor.fetchall()
        return [(str(role), str(content)) for role, content in rows]

    async def create_task(self, task: TaskRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO tasks(
                    id, chat_id, user_id, repository, prompt, status, created_at, updated_at,
                    summary, error, branch, pull_request_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.chat_id,
                    task.user_id,
                    task.repository,
                    task.prompt,
                    task.status,
                    task.created_at,
                    task.updated_at,
                    task.summary,
                    task.error,
                    task.branch,
                    task.pull_request_url,
                ),
            )
            await db.commit()

    async def update_task(self, task_id: str, status: TaskStatus, **fields: str | None) -> None:
        allowed = {"summary", "error", "branch", "pull_request_url"}
        assignments = ["status = ?", "updated_at = ?"]
        values: list[str | None] = [status, _now()]
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported task field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(task_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
                values,
            )
            await db.commit()

    async def latest_task(self, chat_id: int) -> TaskRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE chat_id = ? ORDER BY created_at DESC LIMIT 1",
                (chat_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return TaskRecord(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            repository=row["repository"],
            prompt=row["prompt"],
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            summary=row["summary"],
            error=row["error"],
            branch=row["branch"],
            pull_request_url=row["pull_request_url"],
        )

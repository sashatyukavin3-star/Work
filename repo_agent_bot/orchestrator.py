from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, Message

from .agent import CodingAgent
from .config import Settings
from .database import Database
from .models import GitHubRepository, TaskRecord, TaskStatus
from .repository import RepositoryClient
from .sandbox import CommandSandbox

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short_error(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    value = " ".join(str(exc).split())
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    return value[:800] or type(exc).__name__


async def send_long_message(bot: Bot, chat_id: int, text: str) -> None:
    text = text.strip()
    if not text:
        return
    while text:
        if len(text) <= 3900:
            chunk, text = text, ""
        else:
            split_at = text.rfind("\n", 0, 3900)
            if split_at < 1000:
                split_at = 3900
            chunk, text = text[:split_at], text[split_at:].lstrip()
        await bot.send_message(chat_id, chunk)


class ProgressMessage:
    def __init__(self, bot: Bot, message: Message, task_id: str) -> None:
        self.bot = bot
        self.chat_id = message.chat.id
        self.message_id = message.message_id
        self.task_id = task_id
        self.last_update = 0.0
        self.last_text = ""

    async def update(self, text: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_update < 2.5:
            return
        rendered = f"Задача {self.task_id[:8]}\n{text}"
        if rendered == self.last_text:
            return
        try:
            await self.bot.edit_message_text(
                rendered,
                chat_id=self.chat_id,
                message_id=self.message_id,
            )
            self.last_text = rendered
            self.last_update = now
        except TelegramAPIError:
            logger.debug("Could not update progress message", exc_info=True)


class TaskManager:
    def __init__(self, settings: Settings, database: Database, bot: Bot) -> None:
        self.settings = settings
        self.database = database
        self.bot = bot
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_tasks)
        self.submit_lock = asyncio.Lock()
        self.active: dict[int, asyncio.Task[None]] = {}

    def is_active(self, chat_id: int) -> bool:
        task = self.active.get(chat_id)
        return bool(task and not task.done())

    async def submit(
        self,
        source_message: Message,
        repository: GitHubRepository,
        prompt: str,
    ) -> str | None:
        async with self.submit_lock:
            return await self._submit_locked(source_message, repository, prompt)

    async def _submit_locked(
        self,
        source_message: Message,
        repository: GitHubRepository,
        prompt: str,
    ) -> str | None:
        chat_id = source_message.chat.id
        if self.is_active(chat_id):
            await source_message.answer(
                "Предыдущая задача ещё выполняется. Используйте /status или /cancel."
            )
            return None

        task_id = uuid.uuid4().hex
        created = _now()
        user_id = source_message.from_user.id if source_message.from_user else chat_id
        record = TaskRecord(
            id=task_id,
            chat_id=chat_id,
            user_id=user_id,
            repository=repository.slug,
            prompt=prompt,
            status=TaskStatus.QUEUED,
            created_at=created,
            updated_at=created,
        )
        await self.database.create_task(record)
        history = await self.database.conversation_context(chat_id, limit=8)
        await self.database.add_conversation_message(chat_id, "user", prompt)
        agent_request = self._request_with_context(history, prompt)
        status_message = await source_message.answer(
            f"Задача {task_id[:8]} принята в очередь.\nРепозиторий: {repository.slug}"
        )
        progress = ProgressMessage(self.bot, status_message, task_id)
        task = asyncio.create_task(
            self._execute(record, repository, agent_request, progress),
            name=f"repo-agent-{task_id}",
        )
        self.active[chat_id] = task
        task.add_done_callback(lambda finished, cid=chat_id: self._task_done(cid, finished))
        return task_id

    async def cancel(self, chat_id: int) -> bool:
        task = self.active.get(chat_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    def _task_done(self, chat_id: int, task: asyncio.Task[None]) -> None:
        if self.active.get(chat_id) is task:
            self.active.pop(chat_id, None)
        if not task.cancelled() and (error := task.exception()):
            logger.error(
                "Background task failed unexpectedly",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _execute(
        self,
        record: TaskRecord,
        repository: GitHubRepository,
        agent_request: str,
        progress: ProgressMessage,
    ) -> None:
        workspace = self.settings.workspaces_dir / record.id
        repository_root = workspace / "repository"
        try:
            async with self.semaphore:
                await self.database.update_task(record.id, TaskStatus.RUNNING)
                await progress.update("Клонирую репозиторий…", force=True)
                client = RepositoryClient(
                    self.settings.github_token,
                    command_timeout=self.settings.command_timeout_seconds,
                )
                base_branch = await client.clone(repository, repository_root)
                branch = await client.create_work_branch(repository_root, record.id)
                await self.database.update_task(record.id, TaskStatus.RUNNING, branch=branch)

                mount_workspace = self._host_workspace(repository_root)
                sandbox = CommandSandbox(
                    mode=self.settings.sandbox_mode,
                    workspace=repository_root,
                    mount_workspace=mount_workspace,
                    image=self.settings.sandbox_image,
                    memory=self.settings.sandbox_memory,
                    cpus=self.settings.sandbox_cpus,
                    network=self.settings.sandbox_network,
                    command_timeout=self.settings.command_timeout_seconds,
                )
                if not self.settings.ai_api_key:
                    raise RuntimeError("AI_API_KEY is not configured")

                async with sandbox:
                    agent = CodingAgent(
                        api_key=self.settings.ai_api_key,
                        base_url=self.settings.ai_base_url,
                        model=self.settings.ai_model,
                        max_steps=self.settings.ai_max_steps,
                        workspace=repository_root,
                        sandbox=sandbox,
                        progress=progress.update,
                    )
                    result = await asyncio.wait_for(
                        agent.run(repository, agent_request),
                        timeout=self.settings.task_timeout_seconds,
                    )

                await progress.update("Публикую результат…", force=True)
                publication = await client.publish(
                    root=repository_root,
                    repository=repository,
                    base_branch=base_branch,
                    branch=branch,
                    task_id=record.id,
                    prompt=record.prompt,
                    result=result,
                    create_pr=self.settings.github_create_pr,
                )
                await self._send_result(record, repository_root, result, publication)
                await self.database.add_conversation_message(
                    record.chat_id, "assistant", result.summary
                )
                await self.database.update_task(
                    record.id,
                    TaskStatus.SUCCEEDED,
                    summary=result.summary,
                    branch=publication.branch,
                    pull_request_url=publication.pull_request_url,
                )
                await progress.update("Готово ✅", force=True)
        except asyncio.CancelledError:
            await self.database.update_task(
                record.id, TaskStatus.CANCELLED, error="Cancelled by user"
            )
            await progress.update("Отменено пользователем", force=True)
            raise
        except Exception as exc:
            error = _short_error(
                exc,
                (
                    self.settings.telegram_bot_token,
                    self.settings.ai_api_key,
                    self.settings.github_token,
                ),
            )
            logger.error("Task %s failed (%s): %s", record.id, type(exc).__name__, error)
            await self.database.update_task(record.id, TaskStatus.FAILED, error=error)
            await progress.update("Завершено с ошибкой ❌", force=True)
            await send_long_message(
                self.bot,
                record.chat_id,
                f"Не удалось выполнить задачу {record.id[:8]}.\n{error}\n\n"
                "Проверьте /status, настройки доступа, AI API и журнал сервиса.",
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    async def _send_result(self, record, repository_root, result, publication) -> None:
        lines = [
            f"Результат задачи {record.id[:8]}",
            f"Репозиторий: {record.repository}",
            "",
            result.summary,
        ]
        if result.tests:
            lines.extend(["", "Проверки:", result.tests])
        if result.changed_files:
            shown = result.changed_files[:30]
            lines.extend(["", "Изменённые файлы:", *[f"• {name}" for name in shown]])
            if len(result.changed_files) > len(shown):
                lines.append(f"…ещё {len(result.changed_files) - len(shown)}")
        if publication.pull_request_url:
            lines.extend(["", f"Pull request: {publication.pull_request_url}"])
        elif publication.branch:
            lines.extend(["", f"Ветка: {publication.branch}"])
        await send_long_message(self.bot, record.chat_id, "\n".join(lines))

        artifact_limit = self.settings.max_telegram_artifact_mb * 1024 * 1024
        for relative in result.artifacts:
            path = (repository_root / relative).resolve()
            if not path.is_file() or repository_root.resolve() not in path.parents:
                continue
            if path.stat().st_size > artifact_limit:
                await self.bot.send_message(
                    record.chat_id,
                    f"Артефакт {relative} слишком большой для Telegram "
                    f"({path.stat().st_size // (1024 * 1024)} МБ).",
                )
                continue
            await self.bot.send_document(
                record.chat_id,
                FSInputFile(path, filename=path.name),
                caption=f"Артефакт: {relative}",
            )

        if publication.patch_path and publication.patch_path.is_file():
            if publication.patch_path.stat().st_size <= artifact_limit:
                await self.bot.send_document(
                    record.chat_id,
                    FSInputFile(publication.patch_path, filename=f"{record.id[:8]}.patch"),
                    caption="Git patch с изменениями",
                )

    def _host_workspace(self, repository_root: Path) -> Path:
        if not self.settings.sandbox_host_data_dir:
            return repository_root
        relative = repository_root.resolve().relative_to(self.settings.data_dir)
        return self.settings.sandbox_host_data_dir / relative

    @staticmethod
    def _request_with_context(history: list[tuple[str, str]], current: str) -> str:
        if not history:
            return current
        lines = ["Previous Telegram conversation about this repository:"]
        for role, content in history:
            label = "User" if role == "user" else "Agent"
            lines.append(f"{label}: {content}")
        lines.extend(["", "Current user request:", current])
        return "\n".join(lines)

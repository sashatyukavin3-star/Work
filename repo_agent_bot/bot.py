from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from .config import Settings
from .database import Database
from .github_url import extract_github_repository, repository_is_allowed
from .models import TaskStatus
from .orchestrator import TaskManager


class BotHandlers:
    def __init__(self, settings: Settings, database: Database, task_manager: TaskManager) -> None:
        self.settings = settings
        self.database = database
        self.task_manager = task_manager
        self.router = Router()
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.help, Command("help"))
        self.router.message.register(self.status, Command("status"))
        self.router.message.register(self.cancel, Command("cancel"))
        self.router.message.register(self.reset, Command("reset"))
        self.router.message.register(self.repo, Command("repo"))
        self.router.message.register(self.on_text, F.text)

    @staticmethod
    def commands() -> list[BotCommand]:
        return [
            BotCommand(command="start", description="Как пользоваться ботом"),
            BotCommand(command="status", description="Статус последней задачи"),
            BotCommand(command="repo", description="Активный репозиторий"),
            BotCommand(command="cancel", description="Остановить текущую задачу"),
            BotCommand(command="reset", description="Сбросить репозиторий и диалог"),
            BotCommand(command="help", description="Помощь и примеры"),
        ]

    async def _authorized(self, message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        if user_id in self.settings.telegram_allowed_users:
            return True
        await message.answer(
            "Доступ к агенту закрыт.\n"
            f"Ваш Telegram user ID: {user_id}\n"
            "Администратор должен добавить его в TELEGRAM_ALLOWED_USERS."
        )
        return False

    async def start(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        await message.answer(
            "Я — coding agent для GitHub-репозиториев.\n\n"
            "1. Пришлите ссылку вида https://github.com/owner/repository\n"
            "2. Следующим сообщением опишите нужный продукт или изменение. Можно отправить "
            "ссылку и задачу одним сообщением.\n"
            "3. Я изучу код, внесу изменения, выполню проверки, создам ветку/PR и пришлю "
            "доступные артефакты.\n\n"
            "Пример:\n"
            "https://github.com/acme/mobile-app\n"
            "Добавь авторизацию, тесты и собери APK"
        )

    async def help(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        await self.start(message)

    async def status(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        task = await self.database.latest_task(message.chat.id)
        if not task:
            await message.answer("В этом чате ещё не было задач.")
            return
        labels = {
            TaskStatus.QUEUED: "в очереди",
            TaskStatus.RUNNING: "выполняется",
            TaskStatus.SUCCEEDED: "готово",
            TaskStatus.FAILED: "ошибка",
            TaskStatus.CANCELLED: "отменено",
        }
        lines = [
            f"Задача: {task.id[:8]}",
            f"Статус: {labels[task.status]}",
            f"Репозиторий: {task.repository}",
        ]
        if task.pull_request_url:
            lines.append(f"Pull request: {task.pull_request_url}")
        if task.error:
            lines.append(f"Ошибка: {task.error}")
        await message.answer("\n".join(lines))

    async def cancel(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        if await self.task_manager.cancel(message.chat.id):
            await message.answer("Останавливаю текущую задачу…")
        else:
            await message.answer("Активной задачи нет.")

    async def reset(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        if self.task_manager.is_active(message.chat.id):
            await message.answer("Сначала завершите задачу или используйте /cancel.")
            return
        await self.database.clear_repository(message.chat.id)
        await message.answer("Репозиторий и контекст диалога сброшены. Пришлите новую ссылку.")

    async def repo(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        repository = await self.database.get_repository(message.chat.id)
        if repository:
            await message.answer(f"Активный репозиторий: {repository.web_url}")
        else:
            await message.answer("Репозиторий не выбран. Пришлите ссылку GitHub.")

    async def on_text(self, message: Message) -> None:
        if not await self._authorized(message):
            return
        text = (message.text or "").strip()
        repository, request = extract_github_repository(text)
        if repository:
            if not repository_is_allowed(repository, self.settings.github_repository_allowlist):
                await message.answer(
                    f"Репозиторий {repository.slug} не разрешён. Добавьте владельца или точный "
                    "owner/repository в GITHUB_REPOSITORY_ALLOWLIST."
                )
                return
            if self.task_manager.is_active(message.chat.id):
                await message.answer("Сначала завершите текущую задачу или используйте /cancel.")
                return
            await self.database.set_repository(
                message.chat.id,
                message.from_user.id if message.from_user else message.chat.id,
                repository,
            )
            if not request:
                await message.answer(
                    f"Репозиторий выбран: {repository.slug}\n"
                    "Что нужно создать, изменить, проверить или собрать?"
                )
                return
        else:
            repository = await self.database.get_repository(message.chat.id)

        if not repository:
            await message.answer(
                "Сначала пришлите ссылку на GitHub-репозиторий, затем опишите задачу."
            )
            return
        if not request:
            await message.answer("Опишите задачу текстом.")
            return
        await self.task_manager.submit(message, repository, request)

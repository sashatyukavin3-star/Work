from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from .bot import BotHandlers
from .config import Settings
from .database import Database
from .orchestrator import TaskManager


async def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = Database(str(settings.database_path))
    await database.initialize()

    bot = Bot(token=settings.telegram_bot_token)
    manager = TaskManager(settings, database, bot)
    handlers = BotHandlers(settings, database, manager)
    dispatcher = Dispatcher()
    dispatcher.include_router(handlers.router)

    await bot.set_my_commands(handlers.commands())
    logging.getLogger(__name__).info("Starting Repo Agent Bot with long polling")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    run()

"""Точка входу: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.config import Config, ConfigError, load_config
from bot.database.database import Database
from bot.handlers import errors, fallback
from bot.handlers.admin import (
    comments as admin_comments,
    delivery as admin_delivery,
    orders as admin_orders,
    panel as admin_panel,
    practicals as admin_practicals,
    settings as admin_settings,
    statistics as admin_statistics,
)
from bot.handlers.user import (
    comments as user_comments,
    my_orders as user_my_orders,
    orders as user_orders,
    start as user_start,
    subjects as user_subjects,
)
from bot.middlewares.user import UserRegistrationMiddleware

logger = logging.getLogger("bot")


def create_dispatcher(config: Config, db: Database) -> Dispatcher:
    """Збирає Dispatcher (окремо від запуску — зручно для тестів)."""
    dp = Dispatcher(storage=MemoryStorage(), config=config, db=db)
    dp.update.outer_middleware(UserRegistrationMiddleware(db))
    dp.include_routers(
        errors.router,
        user_start.router,  # /start, /cancel мають спрацьовувати першими, у будь-якому стані
        admin_panel.router,
        admin_practicals.router,
        admin_orders.router,
        admin_delivery.router,
        admin_comments.router,
        admin_statistics.router,
        admin_settings.router,
        user_subjects.router,
        user_orders.router,
        user_my_orders.router,
        user_comments.router,
        fallback.router,  # завжди останнім
    )
    return dp


async def setup_commands(bot: Bot, config: Config) -> None:
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Головне меню"),
                BotCommand(command="cancel", description="Скасувати поточну дію"),
            ],
            scope=BotCommandScopeDefault(),
        )
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Головне меню"),
                BotCommand(command="admin", description="Адмін-панель"),
                BotCommand(command="cancel", description="Скасувати поточну дію"),
            ],
            scope=BotCommandScopeChat(chat_id=config.admin_id),
        )
    except TelegramAPIError as exc:
        # Напр., адміністратор ще не натискав /start у боті — не критично.
        logger.warning("Не вдалося встановити команди бота: %s", exc)


async def run() -> None:
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = create_dispatcher(config, db)
    try:
        me = await bot.get_me()
        logger.info("Бот запущено: @%s", me.username)
        await setup_commands(bot, config)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await db.close()
        logger.info("Бот зупинено")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    try:
        asyncio.run(run())
    except ConfigError as exc:
        logger.error("Помилка конфігурації: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Зупинено користувачем")


if __name__ == "__main__":
    main()

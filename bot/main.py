"""Точка входу: python -m bot.main"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import ClientSession, ClientTimeout, web

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
from bot.storage import DbStorage

logger = logging.getLogger("bot")


def create_dispatcher(config: Config, db: Database) -> Dispatcher:
    """Збирає Dispatcher (окремо від запуску — зручно для тестів)."""
    dp = Dispatcher(storage=DbStorage(db), config=config, db=db)
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


WEBHOOK_PATH = "/webhook"
KEEPALIVE_INTERVAL = 8 * 60  # Render free присипляє сервіс після 15 хв без вхідних запитів


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _keepalive(url: str) -> None:
    """Самопінг публічної адреси, щоб безкоштовний Render не присипляв сервіс."""
    await asyncio.sleep(60)
    async with ClientSession(timeout=ClientTimeout(total=20)) as session:
        while True:
            try:
                async with session.get(url) as resp:
                    logger.debug("keepalive %s -> %s", url, resp.status)
            except Exception as exc:  # noqa: BLE001 — пінг не має валити бота
                logger.warning("keepalive не вдався: %s", exc)
            await asyncio.sleep(KEEPALIVE_INTERVAL)


async def _wait_for_stop() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def run_webhook(bot: Bot, dp: Dispatcher, config: Config) -> None:
    """Режим для Render: aiohttp-сервер приймає оновлення від Telegram."""
    assert config.webhook_base_url
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=config.webhook_secret
    ).register(app, path=WEBHOOK_PATH)

    runner = web.AppRunner(app)
    await runner.setup()
    # Порт відкриваємо першим — Render чекає на нього під час деплою.
    await web.TCPSite(runner, "0.0.0.0", config.port).start()
    logger.info("HTTP-сервер слухає порт %s", config.port)

    keepalive_task: asyncio.Task[None] | None = None
    try:
        await setup_commands(bot, config)
        await bot.set_webhook(
            url=f"{config.webhook_base_url}{WEBHOOK_PATH}",
            secret_token=config.webhook_secret,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        logger.info("Вебхук встановлено: %s%s", config.webhook_base_url, WEBHOOK_PATH)
        if config.keepalive:
            keepalive_task = asyncio.create_task(_keepalive(f"{config.webhook_base_url}/health"))
        await _wait_for_stop()
    finally:
        if keepalive_task:
            keepalive_task.cancel()
        # Вебхук навмисно НЕ видаляємо: поки сервіс перезапускається, Telegram зберігає оновлення.
        await runner.cleanup()


async def run_polling(bot: Bot, dp: Dispatcher, config: Config) -> None:
    """Локальний режим (без публічної адреси): long polling."""
    await setup_commands(bot, config)
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run() -> None:
    config = load_config()
    db = Database(config.db_path, database_url=config.database_url)
    if config.webhook_base_url and not config.database_url:
        logger.warning(
            "DATABASE_URL не задано: використовується SQLite-файл. На безкоштовному Render "
            "файлова система тимчасова — дані зникнуть після перезапуску! Див. README."
        )
    await db.connect()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = create_dispatcher(config, db)
    try:
        me = await bot.get_me()
        logger.info("Бот запущено: @%s", me.username)
        if config.webhook_base_url:
            await run_webhook(bot, dp, config)
        else:
            await run_polling(bot, dp, config)
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

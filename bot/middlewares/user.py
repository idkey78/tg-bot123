from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database import requests
from bot.database.database import Database

logger = logging.getLogger(__name__)
_REFRESH_SECONDS = 300


class UserRegistrationMiddleware(BaseMiddleware):
    """Реєструє/оновлює користувача в БД при будь-якій взаємодії з ботом."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[int, tuple[tuple[str | None, str], float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not user.is_bot:
            key = (user.username, user.full_name)
            cached = self._cache.get(user.id)
            now = time.monotonic()
            if cached is None or cached[0] != key or now - cached[1] > _REFRESH_SECONDS:
                try:
                    await requests.upsert_user(self.db, user.id, user.username, user.full_name)
                    self._cache[user.id] = (key, now)
                except Exception:  # реєстрація не повинна ламати обробку оновлення
                    logger.exception("Не вдалося зареєструвати користувача %s", user.id)
        return await handler(event, data)

"""Глобальний обробник помилок."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)
router = Router(name="errors")

USER_ERROR = "⚠️ Сталася помилка. Спробуйте ще раз або відкрийте меню через /start."


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    logger.error("Необроблена помилка під час обробки оновлення", exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(USER_ERROR, show_alert=True)
        elif update.message is not None:
            await update.message.answer(USER_ERROR)
    except TelegramAPIError as exc:
        logger.debug("Не вдалося повідомити користувача про помилку: %s", exc)
    return True

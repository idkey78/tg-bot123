"""Сповіщення в Telegram: адміністратору та клієнтам. Помилки доставки не ламають бізнес-логіку."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Sequence, TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from bot.config import Config
from bot.database.models import Comment, Order, OrderFile
from bot.keyboards import admin as admin_kb
from bot.keyboards import user as user_kb
from bot.utils.files import send_stored_file
from bot.utils.formatting import esc
from bot.utils.render import render_admin_notification, status_label

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def _retry(call: Callable[[], Awaitable[T]], attempts: int = 2) -> T:
    """Виконує виклик Telegram API, один раз перечікуючи flood-control."""
    for attempt in range(attempts):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(min(exc.retry_after, 30) + 0.5)
    raise RuntimeError("unreachable")


async def notify_admin_new_order(
    bot: Bot, config: Config, order: Order, files: Sequence[OrderFile] = ()
) -> bool:
    text = render_admin_notification(order, config.timezone, task_files=len(files))
    try:
        try:
            await _retry(
                lambda: bot.send_message(
                    config.admin_id, text, reply_markup=admin_kb.new_order_notice_kb(order)
                )
            )
        except TelegramBadRequest as exc:
            # Напр., BUTTON_USER_PRIVACY_RESTRICTED для tg://user?id=…: шлемо без кнопки.
            logger.warning("Сповіщення з кнопкою не пройшло (%s), шлю без неї", exc)
            await _retry(
                lambda: bot.send_message(
                    config.admin_id,
                    text,
                    reply_markup=admin_kb.new_order_notice_kb(order, with_contact=False),
                )
            )
    except TelegramAPIError:
        logger.exception("Не вдалося сповістити адміністратора про замовлення №%s", order.id)
        return False

    for f in files:
        try:
            caption = f"📎 Файл до замовлення №{order.id}"
            if f.caption:
                caption += f"\n{esc(f.caption)}"
            await _retry(
                lambda f=f, caption=caption: send_stored_file(
                    bot, config.admin_id, f.file_type, f.file_id, caption
                )
            )
        except TelegramAPIError:
            logger.exception("Не вдалося переслати файл %s адміністратору", f.id)
    return True


async def notify_user_status(bot: Bot, order: Order, has_results: bool = False) -> bool:
    text = (
        f"🔔 <b>Оновлення замовлення №{order.id}</b>\n\n"
        f"📝 {esc(order.practical_title)}\n"
        f"📌 Новий статус: <b>{status_label(order.status)}</b>"
    )
    if order.status == "awaiting_payment":
        text += "\n\n<i>Оплата здійснюється особисто — виконавець зв'яжеться з вами.</i>"
    try:
        await _retry(
            lambda: bot.send_message(
                order.user_id, text, reply_markup=user_kb.status_notice_kb(order.id, has_results)
            )
        )
        return True
    except TelegramForbiddenError:
        logger.info("Клієнт %s заблокував бота — статус не доставлено", order.user_id)
    except TelegramAPIError:
        logger.exception("Не вдалося сповістити клієнта %s про статус", order.user_id)
    return False


async def notify_user_comment(bot: Bot, order: Order, comment: Comment) -> bool:
    text = (
        f"💬 <b>Коментар виконавця до замовлення №{order.id}</b>\n"
        f"📝 {esc(order.practical_title)}\n\n{esc(comment.text)}"
    )
    try:
        await _retry(
            lambda: bot.send_message(
                order.user_id, text, reply_markup=user_kb.comment_notice_kb(order.id)
            )
        )
        return True
    except TelegramForbiddenError:
        logger.info("Клієнт %s заблокував бота — коментар не доставлено", order.user_id)
    except TelegramAPIError:
        logger.exception("Не вдалося надіслати коментар клієнту %s", order.user_id)
    return False


async def notify_admin_comment(bot: Bot, config: Config, order: Order, comment: Comment) -> bool:
    who = f"@{esc(order.username)}" if order.username else esc(order.full_name)
    text = (
        f"💬 <b>Новий коментар до замовлення №{order.id}</b>\n"
        f"👤 {who} · 📝 {esc(order.practical_title)}\n\n{esc(comment.text)}"
    )
    try:
        await _retry(
            lambda: bot.send_message(
                config.admin_id, text, reply_markup=admin_kb.admin_comment_notice_kb(order.id)
            )
        )
        return True
    except TelegramAPIError:
        logger.exception("Не вдалося сповістити адміністратора про коментар")
        return False

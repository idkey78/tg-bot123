"""Безпечне редагування/надсилання повідомлень (мінімум засмічення чату)."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


def _not_modified(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


async def safe_answer(
    callback: CallbackQuery, text: str | None = None, show_alert: bool = False
) -> None:
    """answer() без падінь, якщо запит застарів."""
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramAPIError as exc:
        logger.debug("callback.answer не вдався: %s", exc)


async def delete_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as exc:
        logger.debug("Не вдалося видалити повідомлення: %s", exc)


async def show(
    event: CallbackQuery | Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> Message | None:
    """Редагує повідомлення, з якого прийшла кнопка. Якщо редагування неможливе
    (повідомлення видалене/застаріле) — надсилає нове."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        if isinstance(msg, Message):
            try:
                result = await msg.edit_text(text, reply_markup=reply_markup)
                return result if isinstance(result, Message) else msg
            except TelegramBadRequest as exc:
                if _not_modified(exc):
                    return msg
                logger.info("Редагування неможливе (%s), надсилаю нове повідомлення", exc)
        return await event.bot.send_message(event.from_user.id, text, reply_markup=reply_markup)
    return await event.answer(text, reply_markup=reply_markup)


async def edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Редагує повідомлення за id; якщо не вийшло — надсилає нове.
    Повертає id актуального повідомлення."""
    if message_id:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
            return message_id
        except TelegramBadRequest as exc:
            if _not_modified(exc):
                return message_id
            logger.info("Редагування за id неможливе (%s), надсилаю нове", exc)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    return sent.message_id


async def edit_panel(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Оновлює «панель» поточного діалогу (id повідомлення зберігається у FSM)."""
    data = await state.get_data()
    new_id = await edit_message(bot, chat_id, data.get("panel_message_id"), text, reply_markup)
    if new_id != data.get("panel_message_id"):
        await state.update_data(panel_message_id=new_id)


async def present(
    source: CallbackQuery | Message,
    bot: Bot,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Показує екран діалогу: з кнопки — редагуванням її повідомлення,
    з текстового введення — редагуванням збереженої «панелі»."""
    if isinstance(source, CallbackQuery):
        msg = await show(source, text, reply_markup)
        if msg is not None:
            await state.update_data(panel_message_id=msg.message_id)
    else:
        await edit_panel(bot, state, source.chat.id, text, reply_markup)

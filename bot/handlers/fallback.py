"""Обробники «усього іншого»: застарілі кнопки, випадкові повідомлення. Підключати останніми."""
from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.keyboards.user import main_menu_kb
from bot.utils.messages import delete_quietly, safe_answer

router = Router(name="fallback")


@router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await safe_answer(
        callback,
        "Ця кнопка вже неактуальна. Відкрийте головне меню командою /start.",
        show_alert=True,
    )


@router.message()
async def stray_message(message: Message, state: FSMContext, config: Config) -> None:
    if await state.get_state() is not None:
        # Користувач у діалозі, але надіслав щось недоречне — не засмічуємо чат.
        await delete_quietly(message)
        return
    is_admin = bool(message.from_user and message.from_user.id == config.admin_id)
    await message.answer(
        "Скористайтеся меню нижче 👇\nАбо надішліть /start.", reply_markup=main_menu_kb(is_admin)
    )

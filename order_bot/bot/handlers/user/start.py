from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.constants import DEFAULT_HELP_TEXT, SETTING_HELP_TEXT
from bot.database import requests
from bot.database.database import Database
from bot.keyboards.user import help_kb, main_menu_kb
from bot.utils.messages import safe_answer, show

router = Router(name="user_start")

WELCOME = (
    "👋 <b>Вітаємо!</b>\n"
    "Тут ти можеш оформити замовлення на допомогу з навчальними практичними роботами.\n\n"
    "Обери потрібний розділ нижче."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    is_admin = bool(message.from_user and message.from_user.id == config.admin_id)
    await message.answer(WELCOME, reply_markup=main_menu_kb(is_admin))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, config: Config) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    is_admin = bool(message.from_user and message.from_user.id == config.admin_id)
    prefix = "Дію скасовано.\n\n" if had_state else ""
    await message.answer(prefix + WELCOME, reply_markup=main_menu_kb(is_admin))


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    await state.clear()
    await safe_answer(callback)
    await show(callback, WELCOME, main_menu_kb(callback.from_user.id == config.admin_id))


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await safe_answer(callback)
    text = await requests.get_setting(db, SETTING_HELP_TEXT, DEFAULT_HELP_TEXT)
    await show(callback, f"ℹ️ <b>Допомога</b>\n\n{text}", help_kb())


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await safe_answer(callback)

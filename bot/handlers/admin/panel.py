from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.constants import STATUS_NEW
from bot.database import requests
from bot.database.database import Database
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_menu_kb
from bot.utils.messages import safe_answer, show

router = Router(name="admin_panel")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def panel_text(db: Database) -> str:
    new_count = await requests.count_orders(db, status=STATUS_NEW)
    return f"⚙️ <b>АДМІН-ПАНЕЛЬ</b>\n\n🔔 Нових замовлень: <b>{new_count}</b>"


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    await message.answer(await panel_text(db), reply_markup=admin_menu_kb())


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await safe_answer(callback)
    await show(callback, await panel_text(db), admin_menu_kb())

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import Config
from bot.constants import FILE_KIND_RESULT, FILE_KIND_TASK, PAGE_SIZE
from bot.database import requests
from bot.database.database import Database
from bot.keyboards.user import back_to_menu_kb, my_orders_kb, order_detail_kb
from bot.utils.files import send_stored_file
from bot.utils.formatting import esc
from bot.utils.messages import safe_answer, show
from bot.utils.paging import clamp_page, total_pages
from bot.utils.render import render_user_order, render_user_order_line

router = Router(name="user_my_orders")


@router.callback_query(F.data.startswith("my:"))
async def cb_my_orders(
    callback: CallbackQuery, state: FSMContext, db: Database, config: Config
) -> None:
    await state.clear()
    await safe_answer(callback)
    raw = (callback.data or "").split(":")[-1]
    page = int(raw) if raw.isdigit() else 0
    user_id = callback.from_user.id

    total = await requests.count_orders(db, user_id=user_id)
    if total == 0:
        await show(
            callback,
            "📦 <b>Мої замовлення</b>\n\nУ вас ще немає замовлень.",
            back_to_menu_kb(),
        )
        return
    pages = total_pages(total, PAGE_SIZE)
    page = clamp_page(page, pages)
    orders = await requests.list_orders(
        db, user_id=user_id, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )
    body = "\n\n".join(render_user_order_line(o, config.timezone) for o in orders)
    text = f"📦 <b>Мої замовлення</b> · всього {total}\n\n{body}\n\nОберіть замовлення для деталей."
    await show(callback, text, my_orders_kb(orders, page, pages))


@router.callback_query(F.data.startswith("ord:"))
async def cb_order_detail(
    callback: CallbackQuery, state: FSMContext, db: Database, config: Config
) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    order_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    # get_user_order повертає лише власні замовлення — чужі недоступні.
    order = await requests.get_user_order(db, order_id, callback.from_user.id)
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    comments = await requests.count_comments(db, order.id)
    task_files = await requests.count_order_files(db, order.id, FILE_KIND_TASK)
    result_files = await requests.count_order_files(db, order.id, FILE_KIND_RESULT)
    text = render_user_order(
        order, config.timezone, comments=comments, task_files=task_files, result_files=result_files
    )
    await show(callback, text, order_detail_kb(order, page, comments, result_files))


@router.callback_query(F.data.startswith("ordf:"))
async def cb_order_results(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Повторно надсилає клієнту виконану роботу (лише власнику замовлення)."""
    raw = (callback.data or "").split(":")[-1]
    order = await requests.get_user_order(db, int(raw), callback.from_user.id) if raw.isdigit() else None
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    files = await requests.list_order_files(db, order.id, FILE_KIND_RESULT)
    if not files:
        await safe_answer(callback, "Виконану роботу ще не надіслано", show_alert=True)
        return
    await safe_answer(callback, "Надсилаю файли…")
    for f in files:
        try:
            await send_stored_file(
                bot,
                callback.from_user.id,
                f.file_type,
                f.file_id,
                caption=f"📎 Замовлення №{order.id}" + (f"\n{esc(f.caption)}" if f.caption else ""),
            )
        except TelegramAPIError:
            continue

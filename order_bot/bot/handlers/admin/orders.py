"""Адмін: список замовлень, деталі, зміна статусів."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import Config
from bot.constants import (
    FILE_KIND_RESULT,
    FILE_KIND_TASK,
    PAGE_SIZE,
    STATUS_DONE,
    STATUS_LABELS,
)
from bot.database import requests
from bot.database.database import Database
from bot.database.models import Order
from bot.filters.admin import IsAdmin
from bot.keyboards import admin as kb
from bot.services.notifications import notify_user_status
from bot.utils.messages import safe_answer, show
from bot.utils.paging import clamp_page, total_pages
from bot.utils.render import render_admin_order

logger = logging.getLogger(__name__)
router = Router(name="admin_orders")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _filter_title(flt: str) -> str:
    return "Усі" if flt == "all" else STATUS_LABELS.get(flt, flt)


def _parse_ctx(parts: list[str], start: int) -> tuple[str, int]:
    flt = parts[start] if len(parts) > start else "all"
    if flt != "all" and flt not in STATUS_LABELS:
        flt = "all"
    page = int(parts[start + 1]) if len(parts) > start + 1 and parts[start + 1].isdigit() else 0
    return flt, page


@router.callback_query(F.data.startswith("adm:ol:"))
async def cb_list(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await safe_answer(callback)
    flt, page = _parse_ctx((callback.data or "").split(":"), 2)
    status = None if flt == "all" else flt
    total = await requests.count_orders(db, status=status)
    pages = total_pages(total, PAGE_SIZE)
    page = clamp_page(page, pages)
    orders = await requests.list_orders(db, status=status, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if total == 0:
        text = f"📦 <b>Замовлення</b> · {_filter_title(flt)}\n\nЗамовлень немає."
    else:
        text = f"📦 <b>Замовлення</b> · {_filter_title(flt)}\nЗнайдено: {total}"
    await show(callback, text, kb.orders_list_kb(orders, flt, page, pages))


async def render_detail(db: Database, config: Config, order: Order, flt: str, page: int) -> tuple[str, object]:
    comments = await requests.count_comments(db, order.id)
    task_files = await requests.count_order_files(db, order.id, FILE_KIND_TASK)
    result_files = await requests.count_order_files(db, order.id, FILE_KIND_RESULT)
    text = render_admin_order(
        order, config.timezone, comments=comments, task_files=task_files, result_files=result_files
    )
    return text, kb.order_detail_kb(order, flt, page, comments=comments, task_files=task_files)


@router.callback_query(F.data.startswith("adm:o:"))
async def cb_detail(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    order = await requests.get_order(db, int(parts[2])) if len(parts) > 2 and parts[2].isdigit() else None
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    flt, page = _parse_ctx(parts, 3)
    text, markup = await render_detail(db, config, order, flt, page)
    await show(callback, text, markup)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("adm:os:"))
async def cb_set_status(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) < 4 or not parts[2].isdigit() or parts[3] not in STATUS_LABELS:
        await safe_answer(callback, "Некоректна дія", show_alert=True)
        return
    order_id, new_status = int(parts[2]), parts[3]
    flt, page = _parse_ctx(parts, 4)
    order = await requests.get_order(db, order_id)
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    if order.status == new_status:
        await safe_answer(callback, "Цей статус уже встановлено")
        return
    updated = await requests.set_order_status(db, order_id, new_status)
    assert updated is not None
    await safe_answer(callback, f"Статус: {STATUS_LABELS[new_status]}")
    text, markup = await render_detail(db, config, updated, flt, page)
    await show(callback, text, markup)  # type: ignore[arg-type]
    has_results = await requests.count_order_files(db, order_id, FILE_KIND_RESULT) > 0
    await notify_user_status(bot, updated, has_results and new_status == STATUS_DONE)

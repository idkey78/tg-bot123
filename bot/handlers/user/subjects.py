from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.constants import PAGE_SIZE, SUBJECTS
from bot.database import requests
from bot.database.database import Database
from bot.keyboards.user import practical_card_kb, subject_practicals_kb
from bot.utils.formatting import esc
from bot.utils.messages import safe_answer, show
from bot.utils.paging import clamp_page, total_pages
from bot.utils.render import render_practical_card

router = Router(name="user_subjects")


@router.callback_query(F.data.startswith("subj:"))
async def cb_subject(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    subject = SUBJECTS.get(parts[1]) if len(parts) > 1 else None
    if subject is None:
        await safe_answer(callback, "Розділ не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    total = await requests.count_practicals(db, subject=subject.key, only_active=True)
    pages = total_pages(total, PAGE_SIZE)
    page = clamp_page(page, pages)
    items = await requests.list_practicals(
        db, subject=subject.key, only_active=True, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )
    if total == 0:
        text = (
            f"{subject.emoji} <b>{esc(subject.title)}</b>\n\n"
            "📭 Поки що немає доступних практичних робіт.\n"
            "Ви можете надіслати власне завдання — оберіть «Custom-практична»."
        )
    else:
        text = (
            f"{subject.emoji} <b>{esc(subject.title)}</b>\n\n"
            "Оберіть практичну роботу зі списку або надішліть власне завдання "
            "через «Custom-практична»."
        )
    await show(callback, text, subject_practicals_kb(subject.key, items, page, pages))


@router.callback_query(F.data.startswith("prac:"))
async def cb_practical(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    raw, _, raw_page = (callback.data or "").removeprefix("prac:").partition(":")
    practical = await requests.get_practical(db, int(raw)) if raw.isdecimal() else None
    page = int(raw_page) if raw_page.isdecimal() else 0
    if practical is None or not practical.is_active:
        await safe_answer(callback, "Ця практична більше недоступна", show_alert=True)
        return
    await safe_answer(callback)
    await show(
        callback,
        render_practical_card(practical),
        practical_card_kb(practical, page),
    )

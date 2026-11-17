"""Адмін: додавання, перегляд, редагування, активація та видалення практичних."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import Config
from bot.constants import DESCRIPTION_MAX, PAGE_SIZE, PRICE_MAX, SUBJECTS, TITLE_MAX, subject_title
from bot.database import requests
from bot.database.database import Database
from bot.filters.admin import IsAdmin
from bot.keyboards import admin as kb
from bot.states.admin import AddPractical, EditPractical
from bot.utils.formatting import esc, fmt_price
from bot.utils.messages import delete_quietly, edit_message, edit_panel, safe_answer, show
from bot.utils.paging import clamp_page, total_pages
from bot.utils.render import LINE, render_practical_admin

logger = logging.getLogger(__name__)
router = Router(name="admin_practicals")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_create_lock = asyncio.Lock()

EDIT_FIELDS = {"t": "назву", "d": "опис", "p": "ціну"}
EDIT_STATES = {"t": EditPractical.title, "d": EditPractical.description, "p": EditPractical.price}


def _id(callback: CallbackQuery) -> int:
    raw = (callback.data or "").split(":")[-1]
    return int(raw) if raw.isdigit() else 0


def parse_price(text: str) -> int | None:
    cleaned = text.replace(" ", "").replace("грн", "").strip()
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if 0 < value <= PRICE_MAX else None


# ───────────────────────── Додавання ─────────────────────────

def _add_header(step: int) -> str:
    return f"➕ <b>Нова практична</b> · крок {step}/5\n{LINE}\n"


@router.callback_query(F.data == "adm:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(callback)
    await state.set_state(AddPractical.subject)
    msg = await show(callback, _add_header(1) + "Оберіть предмет:", kb.add_subject_kb())
    if msg:
        await state.update_data(panel_message_id=msg.message_id)


@router.callback_query(StateFilter(AddPractical.subject), F.data.startswith("adm:as:"))
async def cb_add_subject(callback: CallbackQuery, state: FSMContext) -> None:
    key = (callback.data or "").split(":")[-1]
    if key not in SUBJECTS:
        await safe_answer(callback, "Невідомий предмет", show_alert=True)
        return
    await safe_answer(callback)
    await state.update_data(subject=key)
    await state.set_state(AddPractical.title)
    await show(
        callback,
        _add_header(2) + f"Предмет: {esc(subject_title(key))}\n\nВведіть <b>назву</b> практичної "
        f"(до {TITLE_MAX} символів):",
        kb.cancel_to_menu_kb(),
    )


@router.message(StateFilter(AddPractical.title), F.text)
async def msg_add_title(message: Message, state: FSMContext, bot: Bot) -> None:
    text = " ".join((message.text or "").split())
    await delete_quietly(message)
    if not text or text.startswith("/") or len(text) > TITLE_MAX:
        await edit_panel(
            bot, state, message.chat.id,
            _add_header(2) + f"⚠️ Назва має бути від 1 до {TITLE_MAX} символів і не починатися з «/».\n\n"
            "Введіть назву ще раз:",
            kb.cancel_to_menu_kb(),
        )
        return
    await state.update_data(title=text)
    await state.set_state(AddPractical.description)
    await edit_panel(
        bot, state, message.chat.id,
        _add_header(3) + f"Назва: <b>{esc(text)}</b>\n\nВведіть <b>опис</b> (до {DESCRIPTION_MAX} символів):",
        kb.cancel_to_menu_kb(),
    )


@router.message(StateFilter(AddPractical.description), F.text)
async def msg_add_description(message: Message, state: FSMContext, bot: Bot) -> None:
    text = (message.text or "").strip()
    await delete_quietly(message)
    if not text or text.startswith("/") or len(text) > DESCRIPTION_MAX:
        await edit_panel(
            bot, state, message.chat.id,
            _add_header(3) + f"⚠️ Опис має бути від 1 до {DESCRIPTION_MAX} символів і не починатися з «/».\n\n"
            "Введіть опис ще раз:",
            kb.cancel_to_menu_kb(),
        )
        return
    await state.update_data(description=text)
    await state.set_state(AddPractical.price)
    await edit_panel(
        bot, state, message.chat.id,
        _add_header(4) + "Вкажіть <b>ціну</b> у гривнях (ціле число), напр. <i>150</i>:",
        kb.cancel_to_menu_kb(),
    )


@router.message(StateFilter(AddPractical.price), F.text)
async def msg_add_price(message: Message, state: FSMContext, bot: Bot) -> None:
    price = parse_price(message.text or "")
    await delete_quietly(message)
    if price is None:
        await edit_panel(
            bot, state, message.chat.id,
            _add_header(4) + f"⚠️ Ціна має бути цілим числом від 1 до {PRICE_MAX}.\n\nВведіть ціну ще раз:",
            kb.cancel_to_menu_kb(),
        )
        return
    await state.update_data(price=price)
    await state.set_state(AddPractical.confirm)
    d = await state.get_data()
    text = (
        _add_header(5) + "Перевірте дані:\n\n"
        f"📚 Предмет: {esc(subject_title(d['subject']))}\n"
        f"🏷 Назва: {esc(d['title'])}\n"
        f"💰 Ціна: {fmt_price(price)}\n\n"
        f"📄 Опис:\n{esc(d['description'])}"
    )
    await edit_panel(bot, state, message.chat.id, text, kb.add_confirm_kb())


@router.message(StateFilter(AddPractical.subject, AddPractical.confirm))
async def msg_add_ignored(message: Message) -> None:
    await delete_quietly(message)


@router.message(StateFilter(AddPractical.title, AddPractical.description, AddPractical.price))
async def msg_add_non_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_quietly(message)
    await edit_panel(
        bot, state, message.chat.id,
        "⚠️ Надішліть відповідь текстом або скасуйте створення.", kb.cancel_to_menu_kb(),
    )


@router.callback_query(StateFilter(AddPractical.confirm), F.data == "adm:aok")
async def cb_add_confirm(
    callback: CallbackQuery, state: FSMContext, db: Database, config: Config
) -> None:
    # Lock + перевірка стану: подвійне натискання не створить дублікат.
    async with _create_lock:
        if await state.get_state() != AddPractical.confirm.state:
            await safe_answer(callback, "Практичну вже створено", show_alert=True)
            return
        data: dict[str, Any] = await state.get_data()
        await state.clear()
        practical = await requests.create_practical(
            db, data["subject"], data["title"], data["description"], int(data["price"])
        )
    await safe_answer(callback, "Створено ✅")
    await show(
        callback,
        "✅ <b>Практичну створено — вона вже доступна користувачам.</b>\n\n"
        + render_practical_admin(practical, config.timezone),
        kb.practical_manage_kb(practical),
    )


# ───────────────────────── Список та перегляд ─────────────────────────

@router.callback_query(F.data.startswith("adm:pl:"))
async def cb_list(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await safe_answer(callback)
    total = await requests.count_practicals(db)
    if total == 0:
        await show(
            callback,
            "📚 <b>Практичні</b>\n\nСписок порожній. Додайте першу практичну.",
            kb.practicals_list_kb([], 0, 1),
        )
        return
    pages = total_pages(total, PAGE_SIZE)
    page = clamp_page(_id(callback), pages)
    items = await requests.list_practicals(db, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    await show(
        callback,
        f"📚 <b>Практичні</b> · всього {total}\n\n🟢 — активна, 🔴 — вимкнена",
        kb.practicals_list_kb(items, page, pages),
    )


async def _show_practical(
    callback: CallbackQuery, db: Database, config: Config, practical_id: int, prefix: str = ""
) -> None:
    practical = await requests.get_practical(db, practical_id)
    if practical is None:
        await show(callback, "⚠️ Практичну не знайдено (можливо, її видалено).", kb.practicals_list_kb([], 0, 1))
        return
    await show(
        callback, prefix + render_practical_admin(practical, config.timezone),
        kb.practical_manage_kb(practical),
    )


@router.callback_query(F.data.regexp(r"^adm:p:\d+$"))
async def cb_view(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    await safe_answer(callback)
    await _show_practical(callback, db, config, _id(callback))


# ───────────────────────── Редагування ─────────────────────────

@router.callback_query(F.data.startswith("adm:pe:"))
async def cb_edit_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    parts = (callback.data or "").split(":")
    field, pid = parts[2], int(parts[3]) if parts[3].isdigit() else 0
    practical = await requests.get_practical(db, pid)
    if field not in EDIT_FIELDS or practical is None:
        await safe_answer(callback, "Практичну не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    await state.clear()
    await state.set_state(EDIT_STATES[field])
    await state.update_data(practical_id=pid)
    current = {"t": esc(practical.title), "d": esc(practical.description), "p": fmt_price(practical.price)}[field]
    msg = await show(
        callback,
        f"✏️ <b>Зміна: {EDIT_FIELDS[field]}</b>\n{LINE}\nПоточне значення:\n{current}\n\nНадішліть нове значення:",
        kb.edit_cancel_kb(pid),
    )
    if msg:
        await state.update_data(panel_message_id=msg.message_id)


async def _finish_edit(
    message: Message, state: FSMContext, bot: Bot, db: Database, config: Config,
    *, title: str | None = None, description: str | None = None, price: int | None = None,
) -> None:
    data = await state.get_data()
    pid = int(data["practical_id"])
    panel_id = data.get("panel_message_id")
    practical = await requests.update_practical(
        db, pid, title=title, description=description, price=price
    )
    await state.clear()
    if practical is None:
        await edit_message(bot, message.chat.id, panel_id, "⚠️ Практичну не знайдено.", kb.practicals_list_kb([], 0, 1))
        return
    await edit_message(
        bot, message.chat.id, panel_id,
        "✅ <b>Збережено</b>\n\n" + render_practical_admin(practical, config.timezone),
        kb.practical_manage_kb(practical),
    )


async def _edit_error(message: Message, state: FSMContext, bot: Bot, text: str) -> None:
    data = await state.get_data()
    await edit_panel(bot, state, message.chat.id, f"⚠️ {text}", kb.edit_cancel_kb(int(data["practical_id"])))


@router.message(StateFilter(EditPractical.title), F.text)
async def msg_edit_title(message: Message, state: FSMContext, bot: Bot, db: Database, config: Config) -> None:
    text = " ".join((message.text or "").split())
    await delete_quietly(message)
    if not text or text.startswith("/") or len(text) > TITLE_MAX:
        await _edit_error(message, state, bot, f"Назва має бути від 1 до {TITLE_MAX} символів. Спробуйте ще раз.")
        return
    await _finish_edit(message, state, bot, db, config, title=text)


@router.message(StateFilter(EditPractical.description), F.text)
async def msg_edit_description(message: Message, state: FSMContext, bot: Bot, db: Database, config: Config) -> None:
    text = (message.text or "").strip()
    await delete_quietly(message)
    if not text or text.startswith("/") or len(text) > DESCRIPTION_MAX:
        await _edit_error(message, state, bot, f"Опис має бути від 1 до {DESCRIPTION_MAX} символів. Спробуйте ще раз.")
        return
    await _finish_edit(message, state, bot, db, config, description=text)


@router.message(StateFilter(EditPractical.price), F.text)
async def msg_edit_price(message: Message, state: FSMContext, bot: Bot, db: Database, config: Config) -> None:
    price = parse_price(message.text or "")
    await delete_quietly(message)
    if price is None:
        await _edit_error(message, state, bot, f"Ціна має бути цілим числом від 1 до {PRICE_MAX}.")
        return
    await _finish_edit(message, state, bot, db, config, price=price)


@router.message(StateFilter(EditPractical))
async def msg_edit_non_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_quietly(message)
    await _edit_error(message, state, bot, "Надішліть нове значення текстом.")


# ───────────────────────── Активація / видалення ─────────────────────────

@router.callback_query(F.data.startswith("adm:ptg:"))
async def cb_toggle(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    practical = await requests.toggle_practical_active(db, _id(callback))
    if practical is None:
        await safe_answer(callback, "Практичну не знайдено", show_alert=True)
        return
    await safe_answer(callback, "Активовано" if practical.is_active else "Деактивовано")
    await show(callback, render_practical_admin(practical, config.timezone), kb.practical_manage_kb(practical))


@router.callback_query(F.data.startswith("adm:pdel:"))
async def cb_delete_ask(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    practical = await requests.get_practical(db, _id(callback))
    if practical is None:
        await safe_answer(callback, "Практичну не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    await show(
        callback,
        f"🗑 <b>Видалити практичну?</b>\n\n#{practical.id} · {esc(practical.title)}\n\n"
        "Вона зникне зі списку користувачів. Історія вже створених замовлень збережеться.",
        kb.delete_confirm_kb(practical.id),
    )


@router.callback_query(F.data.startswith("adm:pdy:"))
async def cb_delete_confirm(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    deleted = await requests.delete_practical(db, _id(callback))
    await safe_answer(callback, "Видалено" if deleted else "Вже видалено")
    total = await requests.count_practicals(db)
    items = await requests.list_practicals(db, limit=PAGE_SIZE)
    await show(
        callback,
        ("🗑 <b>Практичну видалено.</b>\n\n" if deleted else "ℹ️ Практичну вже було видалено.\n\n")
        + f"📚 Практичних: {total}",
        kb.practicals_list_kb(items, 0, total_pages(total, PAGE_SIZE)),
    )

"""Адмін: перегляд файлів клієнта та надсилання виконаної роботи клієнту через бота."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.constants import FILE_KIND_RESULT, FILE_KIND_TASK, STATUS_DONE
from bot.database import requests
from bot.database.database import Database
from bot.filters.admin import IsAdmin
from bot.handlers.admin.orders import render_detail
from bot.keyboards import admin as kb
from bot.services.notifications import notify_user_status
from bot.states.admin import Delivery
from bot.utils.files import extract_file, file_title, send_stored_file
from bot.utils.formatting import esc
from bot.utils.messages import delete_quietly, edit_message, safe_answer, show
from bot.utils.render import LINE

logger = logging.getLogger(__name__)
router = Router(name="admin_delivery")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_delivery_lock = asyncio.Lock()


def _id(callback: CallbackQuery) -> int:
    raw = (callback.data or "").split(":")[-1]
    return int(raw) if raw.isdigit() else 0


def _panel(order_id: int, sent: int, names: list[str], warning: str | None = None) -> tuple[str, object]:
    lines = [
        f"📤 <b>Надсилання роботи · замовлення №{order_id}</b>",
        LINE,
        "Надсилайте сюди файли (документи, фото, відео, аудіо) або текст — "
        "кожне повідомлення <b>одразу</b> доставляється клієнту.",
        "",
        f"Надіслано клієнту: <b>{sent}</b>",
    ]
    for name in names[-8:]:
        lines.append(f"• {name}")
    if sent:
        lines.append("\nКоли все надіслано — натисніть «Готово», щоб позначити замовлення виконаним.")
    if warning:
        lines.append(f"\n⚠️ {warning}")
    return "\n".join(lines), kb.delivery_kb(order_id, sent)


@router.callback_query(F.data.startswith("adm:of:"))
async def cb_client_files(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    order_id = _id(callback)
    files = await requests.list_order_files(db, order_id, FILE_KIND_TASK)
    if not files:
        await safe_answer(callback, "Файлів від клієнта немає", show_alert=True)
        return
    await safe_answer(callback, "Надсилаю файли…")
    for f in files:
        caption = f"📎 Файл до замовлення №{order_id}" + (f"\n{esc(f.caption)}" if f.caption else "")
        try:
            await send_stored_file(bot, callback.from_user.id, f.file_type, f.file_id, caption)
        except TelegramAPIError:
            logger.exception("Не вдалося надіслати файл %s адміністратору", f.id)


@router.callback_query(F.data.startswith("adm:dl:"))
async def cb_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    order = await requests.get_order(db, _id(callback))
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    await state.clear()
    await state.set_state(Delivery.files)
    await state.update_data(order_id=order.id, sent=0, names=[], header_sent=False)
    text, markup = _panel(order.id, 0, [])
    msg = await show(callback, text, markup)  # type: ignore[arg-type]
    if msg:
        await state.update_data(panel_message_id=msg.message_id)


@router.message(StateFilter(Delivery.files))
async def msg_deliver(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    async with _delivery_lock:
        data = await state.get_data()
        order_id = int(data.get("order_id", 0))
        sent = int(data.get("sent", 0))
        names: list[str] = list(data.get("names") or [])
        header_sent = bool(data.get("header_sent"))
        panel_id = data.get("panel_message_id")
        order = await requests.get_order(db, order_id)
        warning: str | None = None

        if order is None:
            await state.clear()
            await edit_message(bot, message.chat.id, panel_id, "⚠️ Замовлення не знайдено.", kb.to_admin_menu_kb())
            return

        if message.text and message.text.startswith("/"):
            warning = "Команди тут не працюють. Надішліть файл/текст або натисніть «До замовлення»."
        else:
            info = extract_file(message)
            try:
                if not header_sent:
                    await bot.send_message(
                        order.user_id,
                        f"📤 <b>Виконавець надсилає вашу роботу</b>\nЗамовлення №{order.id} · "
                        f"{esc(order.practical_title)}",
                    )
                    header_sent = True
                await bot.copy_message(order.user_id, message.chat.id, message.message_id)
            except TelegramForbiddenError:
                warning = "Клієнт заблокував бота — повідомлення не доставлено."
            except TelegramAPIError as exc:
                logger.warning("Не вдалося надіслати роботу клієнту: %s", exc)
                warning = f"Не вдалося надіслати це повідомлення ({esc(exc.message)[:120]})."
            else:
                sent += 1
                if info is not None:
                    await requests.add_order_file(
                        db, order_id=order.id, kind=FILE_KIND_RESULT, file_type=info.file_type,
                        file_id=info.file_id, file_name=info.file_name, caption=info.caption,
                        uploaded_by=message.from_user.id,  # type: ignore[union-attr]
                    )
                    names.append(file_title(info.file_name, info.file_type))
                else:
                    names.append("✉️ повідомлення")
                await delete_quietly(message)
                await state.update_data(sent=sent, names=names, header_sent=header_sent)
                warning = None

        if warning:
            await delete_quietly(message)
        text, markup = _panel(order_id, sent, names, warning)
        new_id = await edit_message(bot, message.chat.id, panel_id, text, markup)  # type: ignore[arg-type]
        if new_id != panel_id:
            await state.update_data(panel_message_id=new_id)


@router.callback_query(StateFilter(Delivery.files), F.data.startswith("adm:dd:"))
async def cb_done(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    async with _delivery_lock:
        if await state.get_state() != Delivery.files.state:
            await safe_answer(callback, "Уже завершено", show_alert=True)
            return
        order_id = _id(callback)
        await state.clear()
        order = await requests.get_order(db, order_id)
        if order is None:
            await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
            return
        changed = order.status != STATUS_DONE
        updated = await requests.set_order_status(db, order_id, STATUS_DONE) if changed else order
    assert updated is not None
    await safe_answer(callback, "Замовлення виконано ✅")
    text, markup = await render_detail(db, config, updated, "all", 0)
    await show(callback, text, markup)  # type: ignore[arg-type]
    if changed:
        await notify_user_status(bot, updated, has_results=True)

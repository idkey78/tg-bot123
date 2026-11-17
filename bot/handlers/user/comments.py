from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.constants import COMMENT_MAX
from bot.database import requests
from bot.database.database import Database
from bot.keyboards.user import comment_prompt_kb, comments_kb
from bot.services.notifications import notify_admin_comment
from bot.states.order import CommentFlow
from bot.utils.messages import delete_quietly, edit_message, edit_panel, safe_answer, show
from bot.utils.render import render_comments

logger = logging.getLogger(__name__)
router = Router(name="user_comments")

PROMPT = (
    "✍️ <b>Новий коментар</b>\n\n"
    "Напишіть повідомлення одним текстом (до {max} символів) — виконавець отримає його "
    "в Telegram. Тут можна уточнити деталі практичної."
)


def _order_id(callback: CallbackQuery) -> int:
    raw = (callback.data or "").split(":")[-1]
    return int(raw) if raw.isdigit() else 0


@router.callback_query(F.data.startswith("cm:v:"))
async def cb_view(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    order = await requests.get_user_order(db, _order_id(callback), callback.from_user.id)
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    comments = await requests.list_comments(db, order.id, limit=10)
    total = await requests.count_comments(db, order.id)
    text = render_comments(order, comments, config.timezone, viewer_is_admin=False, total=total)
    await show(callback, text, comments_kb(order.id))


@router.callback_query(F.data.startswith("cm:w:"))
async def cb_write(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    order = await requests.get_user_order(db, _order_id(callback), callback.from_user.id)
    if order is None:
        await safe_answer(callback, "Замовлення не знайдено", show_alert=True)
        return
    await safe_answer(callback)
    await state.clear()
    await state.set_state(CommentFlow.text)
    await state.update_data(order_id=order.id)
    msg = await show(callback, PROMPT.format(max=COMMENT_MAX), comment_prompt_kb(order.id))
    if msg is not None:
        await state.update_data(panel_message_id=msg.message_id)


@router.message(StateFilter(CommentFlow.text), F.text)
async def msg_comment(
    message: Message, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    order_id = int(data.get("order_id", 0))
    text = (message.text or "").strip()
    user_id = message.from_user.id  # type: ignore[union-attr]
    await delete_quietly(message)

    error = None
    if text.startswith("/"):
        error = "Команди тут не працюють. Напишіть текст коментаря або скасуйте."
    elif len(text) > COMMENT_MAX:
        error = f"Занадто довго ({len(text)} із {COMMENT_MAX} символів). Скоротіть коментар."
    if error:
        await edit_panel(
            bot, state, message.chat.id,
            PROMPT.format(max=COMMENT_MAX) + f"\n\n⚠️ {error}", comment_prompt_kb(order_id),
        )
        return

    comment = await requests.add_comment(
        db, order_id=order_id, author_id=user_id, is_admin=False, text=text, as_user_id=user_id
    )
    order = await requests.get_user_order(db, order_id, user_id)
    panel_id = data.get("panel_message_id")
    await state.clear()
    if comment is None or order is None:
        await edit_message(
            bot, message.chat.id, panel_id, "⚠️ Не вдалося додати коментар. Спробуйте ще раз.",
            comments_kb(order_id),
        )
        return

    comments = await requests.list_comments(db, order.id, limit=10)
    total = await requests.count_comments(db, order.id)
    view = render_comments(order, comments, config.timezone, viewer_is_admin=False, total=total)
    await edit_message(
        bot, message.chat.id, panel_id, "✅ <b>Коментар надіслано</b>\n\n" + view,
        comments_kb(order.id),
    )
    await notify_admin_comment(bot, config, order, comment)


@router.message(StateFilter(CommentFlow.text))
async def msg_comment_invalid(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await delete_quietly(message)
    await edit_panel(
        bot, state, message.chat.id,
        PROMPT.format(max=COMMENT_MAX) + "\n\n⚠️ Надішліть коментар текстом.",
        comment_prompt_kb(int(data.get("order_id", 0))),
    )

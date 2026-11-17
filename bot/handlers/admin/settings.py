from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.constants import (
    DEFAULT_HELP_TEXT,
    HELP_TEXT_MAX,
    SETTING_HELP_TEXT,
    SETTING_ORDERS_ENABLED,
)
from bot.database import requests
from bot.database.database import Database
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import settings_cancel_kb, settings_kb
from bot.states.admin import SettingsEdit
from bot.utils.formatting import esc, fmt_duration
from bot.utils.messages import delete_quietly, edit_message, edit_panel, safe_answer, show

router = Router(name="admin_settings")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _screen(db: Database, config: Config) -> tuple[str, object]:
    enabled = await requests.get_setting(db, SETTING_ORDERS_ENABLED, "1") == "1"
    help_text = await requests.get_setting(db, SETTING_HELP_TEXT, DEFAULT_HELP_TEXT)
    preview = help_text if len(help_text) <= 400 else help_text[:399] + "…"
    text = (
        "⚙️ <b>Налаштування</b>\n───────────────\n"
        f"📥 Прийом замовлень: <b>{'🟢 увімкнено' if enabled else '🔴 призупинено'}</b>\n"
        f"⏱ Ліміт: {config.order_limit} замовлення за "
        f"{fmt_duration(config.order_window_seconds)} (ковзне вікно)\n\n"
        f"ℹ️ <b>Текст розділу «Допомога»</b> (HTML-теги тут показано як є):\n{esc(preview)}"
    )
    return text, settings_kb(enabled)


@router.callback_query(F.data == "adm:settings")
async def cb_settings(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    await safe_answer(callback)
    text, markup = await _screen(db, config)
    await show(callback, text, markup)  # type: ignore[arg-type]


@router.callback_query(F.data == "adm:set:toggle")
async def cb_toggle(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    enabled = await requests.get_setting(db, SETTING_ORDERS_ENABLED, "1") == "1"
    await requests.set_setting(db, SETTING_ORDERS_ENABLED, "0" if enabled else "1")
    await safe_answer(callback, "Прийом призупинено" if enabled else "Прийом відновлено")
    text, markup = await _screen(db, config)
    await show(callback, text, markup)  # type: ignore[arg-type]


@router.callback_query(F.data == "adm:set:help")
async def cb_help_start(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_answer(callback)
    await state.clear()
    await state.set_state(SettingsEdit.help_text)
    msg = await show(
        callback,
        "✏️ <b>Текст розділу «Допомога»</b>\n\n"
        f"Надішліть новий текст (до {HELP_TEXT_MAX} символів). Жирний шрифт, курсив тощо "
        "можна робити прямо в Telegram — вони збережуться.\nДобре додати свої контакти для зв'язку.",
        settings_cancel_kb(),
    )
    if msg:
        await state.update_data(panel_message_id=msg.message_id)


@router.message(StateFilter(SettingsEdit.help_text), F.text)
async def msg_help(message: Message, state: FSMContext, bot: Bot, db: Database, config: Config) -> None:
    # html_text зберігає форматування, яке адмін зробив у самому Telegram (жирний, курсив тощо).
    text = (message.html_text or "").strip()
    raw = (message.text or "").strip()
    await delete_quietly(message)
    if not raw or raw.startswith("/") or len(text) > HELP_TEXT_MAX:
        await edit_panel(
            bot, state, message.chat.id,
            f"⚠️ Текст має бути від 1 до {HELP_TEXT_MAX} символів. Спробуйте ще раз.",
            settings_cancel_kb(),
        )
        return
    panel_id = (await state.get_data()).get("panel_message_id")
    await requests.set_setting(db, SETTING_HELP_TEXT, text)
    await state.clear()
    screen, markup = await _screen(db, config)
    await edit_message(bot, message.chat.id, panel_id, "✅ <b>Збережено</b>\n\n" + screen, markup)  # type: ignore[arg-type]


@router.message(StateFilter(SettingsEdit.help_text))
async def msg_help_invalid(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_quietly(message)
    await edit_panel(bot, state, message.chat.id, "⚠️ Надішліть текст повідомленням.", settings_cancel_kb())

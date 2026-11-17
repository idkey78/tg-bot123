"""Оформлення замовлення: вибір оплати, Custom-практична з файлами, ім'я/група, підтвердження."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import Config
from bot.constants import (
    CUSTOM_OFFER_MAX,
    DESCRIPTION_MAX,
    MAX_TASK_FILES,
    PAYMENT_CUSTOM,
    PAYMENT_REGULAR,
    SETTING_ORDERS_ENABLED,
    STUDENT_INFO_MAX,
    SUBJECTS,
    subject_label,
    subject_title,
)
from bot.database import requests
from bot.database.database import Database
from bot.database.models import Practical
from bot.keyboards import user as kb
from bot.services.notifications import notify_admin_new_order
from bot.states.order import OrderFlow
from bot.utils.files import extract_file, file_title
from bot.utils.formatting import esc, fmt_duration, fmt_price
from bot.utils.messages import delete_quietly, edit_panel, present, safe_answer, show
from bot.utils.render import LINE, PAY_NOTE, render_summary, render_user_order

logger = logging.getLogger(__name__)
router = Router(name="user_orders")

# Альбом з кількох фото надходить як кілька одночасних повідомлень —
# серіалізуємо оновлення списку файлів у межах користувача.
_file_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

Screen = tuple[str, InlineKeyboardMarkup]


# ───────────────────────── Допоміжні функції ─────────────────────────

def limit_text(config: Config, retry_after: int) -> str:
    hours = config.order_window_seconds // 3600
    return (
        "⏳ <b>Ліміт замовлень</b>\n\n"
        f"Можна створити не більше {config.order_limit} замовлень за {hours} год.\n"
        f"Нове замовлення буде доступне через <b>{fmt_duration(retry_after)}</b>."
    )


async def _precheck(callback: CallbackQuery, db: Database, config: Config) -> bool:
    """Перевіряє, чи можна починати оформлення (прийом увімкнено, ліміт не вичерпано)."""
    if await requests.get_setting(db, SETTING_ORDERS_ENABLED, "1") != "1":
        await show(
            callback,
            "⏸ <b>Прийом замовлень тимчасово призупинено</b>\n\nСпробуйте, будь ласка, пізніше.",
            kb.back_to_menu_kb(),
        )
        return False
    retry = await requests.get_limit_retry_after(
        db, callback.from_user.id, config.order_limit, config.order_window_seconds
    )
    if retry:
        await show(callback, limit_text(config, retry), kb.back_to_menu_kb())
        return False
    return True


async def _begin(callback: CallbackQuery, state: FSMContext, **extra: Any) -> None:
    await state.clear()
    msg = callback.message
    values: dict[str, Any] = {
        "panel_message_id": msg.message_id if isinstance(msg, Message) else None,
        "draft_token": uuid.uuid4().hex,
        "editing": False,
        "files": [],
        "custom_description": None,
        "student_info": None,
        "custom_offer": None,
        "payment_type": None,
    }
    # extra може перевизначати значення за замовчуванням (напр. payment_type для Custom).
    values.update(extra)
    await state.update_data(**values)


async def _practical(db: Database, data: dict[str, Any]) -> Practical | None:
    pid = data.get("practical_id")
    return await requests.get_practical(db, int(pid)) if pid else None


def _ready(data: dict[str, Any]) -> bool:
    """Чи достатньо даних для підсумку/створення замовлення."""
    payment = data.get("payment_type")
    if payment == PAYMENT_CUSTOM:
        if not (data.get("custom_offer") or "").strip():
            return False
    elif payment != PAYMENT_REGULAR:
        return False
    if data.get("custom_practical"):
        return bool(data.get("files") or data.get("custom_description"))
    return bool(data.get("practical_id"))


# ───────────────────────── Екрани ─────────────────────────

def screen_payment(practical: Practical, editing: bool) -> Screen:
    text = (
        "🔷 <b>Оформлення замовлення</b>\n"
        f"{LINE}\n"
        f"📚 {esc(subject_title(practical.subject))}\n"
        f"📝 {esc(practical.title)}\n"
        f"💰 Ціна: <b>{fmt_price(practical.price)}</b>\n\n"
        "Оберіть варіант оплати.\n"
        f"{PAY_NOTE}"
    )
    return text, kb.payment_choice_kb(practical, editing)


def screen_regular(practical: Practical) -> Screen:
    text = (
        "💵 <b>Звичайна оплата</b>\n"
        f"{LINE}\n"
        f"💰 Ціна: <b>{fmt_price(practical.price)}</b>\n\n"
        "Оплата відбувається <b>особисто</b> між вами та виконавцем. "
        "У боті гроші не приймаються і оплата автоматично не підтверджується.\n\n"
        "Натисніть «Продовжити», щоб перейти до оформлення."
    )
    return text, kb.regular_info_kb()


def screen_offer(data: dict[str, Any], error: str | None = None) -> Screen:
    if data.get("editing"):
        back = "flow:summary"
    elif data.get("custom_practical"):
        back = "flow:files"
    else:
        back = "pay:back"
    hint = (
        "Вкажіть, скільки ви готові заплатити за виконання цієї роботи."
        if data.get("custom_practical")
        else "Запропонуйте свою суму або умови."
    )
    text = (
        "✏️ <b>Custom-пропозиція</b>\n"
        f"{LINE}\n"
        f"{hint}\n"
        f"Напишіть одним повідомленням (до {CUSTOM_OFFER_MAX} символів), "
        "наприклад: <i>150 грн</i>.\n\n"
        "Оплата відбувається особисто, пропозиція не вважається підтвердженою автоматично."
    )
    if error:
        text += f"\n\n⚠️ {error}"
    return text, kb.offer_prompt_kb(back)


def screen_info(data: dict[str, Any], error: str | None = None) -> Screen:
    text = (
        "🎓 <b>Ім'я, прізвище та група</b>\n"
        f"{LINE}\n"
        "Напишіть одним повідомленням, наприклад:\n"
        "<i>Іваненко Іван, ІП-21</i>\n\n"
        "Цей пункт необов'язковий — його можна пропустити."
    )
    if error:
        text += f"\n\n⚠️ {error}"
    return text, kb.info_prompt_kb(bool(data.get("editing")))


def screen_files(data: dict[str, Any], error: str | None = None) -> Screen:
    files = data.get("files") or []
    subject = data.get("subject", "")
    lines = [
        f"📎 <b>Custom-практична</b> · {esc(subject_label(subject))}",
        LINE,
        "Надішліть файл із завданням (документ, фото, відео чи аудіо) — "
        f"можна кілька, до {MAX_TASK_FILES}. Текстом можна додати опис та вимоги.",
        "",
        f"Отримано файлів: <b>{len(files)}</b>",
    ]
    for f in files:
        lines.append(f"• {file_title(f.get('file_name'), f.get('file_type', ''))}")
    if data.get("custom_description"):
        desc = data["custom_description"]
        lines.append(f"\n🗒 Опис: {esc(desc if len(desc) <= 300 else desc[:299] + '…')}")
    lines.append("\nКоли все надіслано — натисніть «Готово».")
    if error:
        lines.append(f"\n⚠️ {error}")
    back = "flow:summary" if data.get("editing") else f"subj:{subject}:0"
    has_content = bool(files or data.get("custom_description"))
    return "\n".join(lines), kb.files_prompt_kb(back, has_content)


async def screen_summary(
    db: Database, data: dict[str, Any], username: str | None, full_name: str, config: Config
) -> Screen:
    practical = None if data.get("custom_practical") else await _practical(db, data)
    text = render_summary(
        data, practical, username=username, full_name=full_name,
        now=int(time.time()), tz=config.timezone,
    )
    return text, kb.summary_kb()


# ───────────────────────── Переходи між кроками ─────────────────────────

async def _abort(source: CallbackQuery | Message, bot: Bot, state: FSMContext, text: str) -> None:
    await present(source, bot, state, text, kb.back_to_menu_kb())
    await state.clear()


async def go_payment(source: CallbackQuery | Message, bot: Bot, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    practical = await _practical(db, data)
    if practical is None or not practical.is_active:
        await _abort(source, bot, state, "⚠️ Ця практична більше недоступна.")
        return
    await state.set_state(OrderFlow.payment)
    text, markup = screen_payment(practical, bool(data.get("editing")))
    await present(source, bot, state, text, markup)


async def go_offer(source: CallbackQuery | Message, bot: Bot, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(OrderFlow.custom_offer)
    text, markup = screen_offer(await state.get_data(), error)
    await present(source, bot, state, text, markup)


async def go_info(source: CallbackQuery | Message, bot: Bot, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(OrderFlow.student_info)
    text, markup = screen_info(await state.get_data(), error)
    await present(source, bot, state, text, markup)


async def go_files(source: CallbackQuery | Message, bot: Bot, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(OrderFlow.custom_files)
    text, markup = screen_files(await state.get_data(), error)
    await present(source, bot, state, text, markup)


async def go_summary(
    source: CallbackQuery | Message, bot: Bot, state: FSMContext, db: Database, config: Config
) -> None:
    await state.update_data(editing=False)
    await state.set_state(OrderFlow.confirm)
    data = await state.get_data()
    user = source.from_user
    assert user is not None
    text, markup = await screen_summary(db, data, user.username, user.full_name, config)
    await present(source, bot, state, text, markup)


async def _after_payment(
    source: CallbackQuery | Message, bot: Bot, state: FSMContext, db: Database, config: Config
) -> None:
    data = await state.get_data()
    if data.get("editing"):
        await go_summary(source, bot, state, db, config)
    else:
        await go_info(source, bot, state)


# ───────────────────────── Початок оформлення ─────────────────────────

@router.callback_query(F.data.startswith("order:"))
async def cb_start_order(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    await state.clear()
    await safe_answer(callback)
    raw = (callback.data or "").split(":")[-1]
    practical = await requests.get_practical(db, int(raw)) if raw.isdigit() else None
    if practical is None or not practical.is_active:
        await show(callback, "⚠️ Ця практична більше недоступна.", kb.back_to_menu_kb())
        return
    if not await _precheck(callback, db, config):
        return
    await _begin(
        callback, state, custom_practical=False, practical_id=practical.id, subject=practical.subject
    )
    await go_payment(callback, bot, state, db)


@router.callback_query(F.data.startswith("cust:"))
async def cb_start_custom(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    await state.clear()
    await safe_answer(callback)
    key = (callback.data or "").split(":")[-1]
    if key not in SUBJECTS:
        await show(callback, "⚠️ Розділ не знайдено.", kb.back_to_menu_kb())
        return
    if not await _precheck(callback, db, config):
        return
    await _begin(
        callback, state, custom_practical=True, practical_id=None, subject=key,
        payment_type=PAYMENT_CUSTOM,
    )
    await go_files(callback, bot, state)


# ───────────────────────── Оплата ─────────────────────────

@router.callback_query(StateFilter(OrderFlow.payment), F.data == "pay:regular")
async def cb_pay_regular(callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    await safe_answer(callback)
    practical = await _practical(db, await state.get_data())
    if practical is None or not practical.is_active:
        await _abort(callback, bot, state, "⚠️ Ця практична більше недоступна.")
        return
    await state.update_data(payment_type=PAYMENT_REGULAR, custom_offer=None)
    text, markup = screen_regular(practical)
    await present(callback, bot, state, text, markup)


@router.callback_query(StateFilter(OrderFlow.payment), F.data == "pay:continue")
async def cb_pay_continue(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    if data.get("payment_type") != PAYMENT_REGULAR:
        await safe_answer(callback, "Спочатку оберіть варіант оплати", show_alert=True)
        return
    await safe_answer(callback)
    await _after_payment(callback, bot, state, db, config)


@router.callback_query(StateFilter(OrderFlow.payment), F.data == "pay:custom")
async def cb_pay_custom(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback)
    await go_offer(callback, bot, state)


@router.callback_query(StateFilter(OrderFlow.payment, OrderFlow.custom_offer), F.data == "pay:back")
async def cb_pay_back(callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    await safe_answer(callback)
    await go_payment(callback, bot, state, db)


@router.message(StateFilter(OrderFlow.custom_offer), F.text)
async def msg_offer(
    message: Message, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    text = (message.text or "").strip()
    await delete_quietly(message)
    if text.startswith("/"):
        await go_offer(message, bot, state, "Команди тут не працюють. Напишіть суму або скасуйте.")
        return
    if len(text) > CUSTOM_OFFER_MAX:
        await go_offer(
            message, bot, state, f"Занадто довго ({len(text)} із {CUSTOM_OFFER_MAX} символів)."
        )
        return
    await state.update_data(payment_type=PAYMENT_CUSTOM, custom_offer=text)
    await _after_payment(message, bot, state, db, config)


@router.message(StateFilter(OrderFlow.custom_offer))
async def msg_offer_invalid(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_quietly(message)
    await go_offer(message, bot, state, "Надішліть пропозицію текстом.")


# ───────────────────────── Файли Custom-практичної ─────────────────────────

@router.message(StateFilter(OrderFlow.custom_files))
async def msg_files(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    assert user is not None
    async with _file_locks[user.id]:
        data = await state.get_data()
        files = list(data.get("files") or [])
        desc = data.get("custom_description") or ""
        error: str | None = None
        info = extract_file(message)
        if info is not None:
            if len(files) >= MAX_TASK_FILES:
                error = f"Максимум {MAX_TASK_FILES} файлів. Натисніть «Готово»."
            else:
                files.append(info.as_dict())
        elif message.text:
            text = message.text.strip()
            if text.startswith("/"):
                error = "Команди тут не працюють. Надішліть файл або опис."
            else:
                new_desc = f"{desc}\n{text}".strip() if desc else text
                if len(new_desc) > DESCRIPTION_MAX:
                    error = f"Опис занадто довгий (максимум {DESCRIPTION_MAX} символів)."
                else:
                    desc = new_desc
        else:
            error = "Підтримуються документи, фото, відео, аудіо та текст."

        if error is None:
            await state.update_data(files=files, custom_description=desc or None)
        data = await state.get_data()
        text_out, markup = screen_files(data, error)
        await delete_quietly(message)
        try:
            await edit_panel(bot, state, message.chat.id, text_out, markup)
        except TelegramAPIError as exc:  # напр., flood-control під час альбому
            logger.info("Не вдалося оновити екран файлів: %s", exc)


@router.callback_query(StateFilter(OrderFlow.custom_files), F.data == "cf:clear")
async def cb_files_clear(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback, "Очищено")
    await state.update_data(files=[], custom_description=None)
    await go_files(callback, bot, state)


@router.callback_query(StateFilter(OrderFlow.custom_files), F.data == "cf:done")
async def cb_files_done(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    if not (data.get("files") or data.get("custom_description")):
        await safe_answer(callback, "Надішліть хоча б один файл або опис завдання", show_alert=True)
        return
    await safe_answer(callback)
    if data.get("editing"):
        if _ready(data):
            await go_summary(callback, bot, state, db, config)
        else:
            await go_offer(callback, bot, state)
    else:
        await go_offer(callback, bot, state)


@router.callback_query(
    StateFilter(OrderFlow.custom_offer, OrderFlow.custom_files, OrderFlow.confirm),
    F.data == "flow:files",
)
async def cb_flow_files(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback)
    await go_files(callback, bot, state)


# ───────────────────────── Ім'я та група ─────────────────────────

@router.message(StateFilter(OrderFlow.student_info), F.text)
async def msg_info(
    message: Message, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    text = " ".join((message.text or "").split())
    await delete_quietly(message)
    if text.startswith("/"):
        await go_info(message, bot, state, "Команди тут не працюють. Напишіть дані або пропустіть.")
        return
    if len(text) > STUDENT_INFO_MAX:
        await go_info(message, bot, state, f"Занадто довго ({len(text)} із {STUDENT_INFO_MAX} символів).")
        return
    await state.update_data(student_info=text)
    await go_summary(message, bot, state, db, config)


@router.message(StateFilter(OrderFlow.student_info))
async def msg_info_invalid(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_quietly(message)
    await go_info(message, bot, state, "Надішліть дані текстом або натисніть «Пропустити».")


@router.callback_query(StateFilter(OrderFlow.student_info), F.data == "info:skip")
async def cb_info_skip(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    await safe_answer(callback)
    await state.update_data(student_info=None)
    await go_summary(callback, bot, state, db, config)


# ───────────────────────── Підсумок, редагування, скасування ─────────────────────────

@router.callback_query(
    StateFilter(
        OrderFlow.payment, OrderFlow.custom_offer, OrderFlow.student_info,
        OrderFlow.custom_files, OrderFlow.confirm,
    ),
    F.data == "flow:summary",
)
async def cb_flow_summary(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    if not _ready(data):
        await safe_answer(callback, "Спочатку заповніть обов'язкові дані (оплата, завдання)", show_alert=True)
        return
    await safe_answer(callback)
    await go_summary(callback, bot, state, db, config)


@router.callback_query(StateFilter(OrderFlow.confirm), F.data == "edit")
async def cb_edit(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback)
    data = await state.get_data()
    text = "✏️ <b>Що бажаєте змінити?</b>"
    await present(callback, bot, state, text, kb.edit_menu_kb(bool(data.get("custom_practical"))))


@router.callback_query(StateFilter(OrderFlow.confirm), F.data == "edit:pay")
async def cb_edit_pay(callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    await safe_answer(callback)
    await state.update_data(editing=True)
    data = await state.get_data()
    if data.get("custom_practical"):
        await go_offer(callback, bot, state)
    else:
        await go_payment(callback, bot, state, db)


@router.callback_query(StateFilter(OrderFlow.confirm), F.data == "edit:info")
async def cb_edit_info(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback)
    await state.update_data(editing=True)
    await go_info(callback, bot, state)


@router.callback_query(StateFilter(OrderFlow.confirm), F.data == "edit:files")
async def cb_edit_files(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await safe_answer(callback)
    data = await state.get_data()
    if not data.get("custom_practical"):
        return
    await state.update_data(editing=True)
    await go_files(callback, bot, state)


@router.callback_query(StateFilter(OrderFlow), F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(callback)
    await show(callback, "❌ <b>Оформлення скасовано</b>\n\nДані не збережено.", kb.back_to_menu_kb())


# ───────────────────────── Підтвердження ─────────────────────────

@router.callback_query(StateFilter(OrderFlow.confirm), F.data == "confirm")
async def cb_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database, config: Config
) -> None:
    data = await state.get_data()
    user = callback.from_user
    token = data.get("draft_token")
    if not token or not _ready(data):
        await state.clear()
        await safe_answer(callback, "Дані застаріли. Почніть оформлення спочатку.", show_alert=True)
        await show(callback, "⚠️ Сесія оформлення застаріла.", kb.back_to_menu_kb())
        return
    if await requests.get_setting(db, SETTING_ORDERS_ENABLED, "1") != "1":
        await state.clear()
        await safe_answer(callback)
        await show(
            callback,
            "⏸ <b>Прийом замовлень тимчасово призупинено</b>\n\nСпробуйте, будь ласка, пізніше.",
            kb.back_to_menu_kb(),
        )
        return
    await safe_answer(callback)

    custom_practical = bool(data.get("custom_practical"))
    result = await requests.create_order(
        db,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        payment_type=data["payment_type"],
        custom_offer=data.get("custom_offer"),
        draft_token=token,
        limit=config.order_limit,
        window_seconds=config.order_window_seconds,
        practical_id=None if custom_practical else int(data["practical_id"]),
        subject=data.get("subject") if custom_practical else None,
        custom_description=data.get("custom_description") if custom_practical else None,
        student_info=data.get("student_info"),
        files=data.get("files") or [] if custom_practical else [],
    )
    await state.clear()

    if result.status == requests.LIMIT_REACHED:
        await show(callback, limit_text(config, result.retry_after), kb.back_to_menu_kb())
        return
    if result.status == requests.UNAVAILABLE:
        await show(callback, "⚠️ Ця практична більше недоступна.", kb.back_to_menu_kb())
        return
    if result.status == requests.INVALID or result.order is None:
        await show(callback, "⚠️ Не вдалося оформити замовлення. Спробуйте ще раз.", kb.back_to_menu_kb())
        return

    order = result.order
    # Для DUPLICATE (повторне натискання) просто повторно показуємо те саме підтвердження.
    details = render_user_order(
        order, config.timezone,
        task_files=len(result.files) if result.status == requests.CREATED else len(data.get("files") or []),
    )
    await show(
        callback,
        f"✅ <b>Замовлення №{order.id} відправлено</b>\n\n{details}\n\n"
        "Виконавець отримав сповіщення. Ви можете залишати коментарі до замовлення "
        "в розділі «Мої замовлення».\n"
        f"{PAY_NOTE}",
        kb.after_order_kb(),
    )
    if result.status == requests.CREATED:
        await notify_admin_new_order(bot, config, order, result.files)

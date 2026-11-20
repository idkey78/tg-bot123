from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup

from bot.constants import SUBJECTS, STATUS_EMOJI
from bot.database.models import Order, Practical
from bot.keyboards.common import btn, pagination_row
from bot.utils.formatting import fmt_price, short


def _kb(rows: list[list]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[btn(s.label, f"subj:{s.key}:0")] for s in SUBJECTS.values()]
    rows.append([btn("ℹ️ Умови та оплата", "terms")])
    rows.append([btn("📦 Мої замовлення", "my:0"), btn("ℹ️ Допомога", "help")])
    if is_admin:
        rows.append([btn("⚙️ Адмін-панель", "adm:menu")])
    return _kb(rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("🏠 Головне меню", "menu")]])


def help_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("🏠 Головне меню", "menu")]])


def subject_practicals_kb(
    subject_key: str, practicals: Sequence[Practical], page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = [
        [btn(f"📝 {short(p.title, 38)} — {fmt_price(p.price)}", f"prac:{p.id}:{page}")]
        for p in practicals
    ]
    rows.append(pagination_row(f"subj:{subject_key}:", page, pages))
    rows.append([btn("✏️ Custom-практична (своє завдання)", f"cust:{subject_key}")])
    rows.append([btn("🏠 Головне меню", "menu")])
    return _kb(rows)


def practical_card_kb(practical: Practical, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if practical.is_active:
        rows.append([btn("✅ Оформити замовлення", f"order:{practical.id}")])
    rows.append([btn("⬅️ Назад до списку", f"subj:{practical.subject}:{page}")])
    return _kb(rows)


def payment_choice_kb(practical: Practical, editing: bool) -> InlineKeyboardMarkup:
    back = "flow:summary" if editing else f"prac:{practical.id}"
    return _kb(
        [
            [btn("💵 Звичайна оплата", "pay:regular")],
            [btn("✏️ Custom-пропозиція", "pay:custom")],
            [btn("⬅️ Назад", back), btn("🏠 Меню", "menu")],
        ]
    )


def regular_info_kb() -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("➡️ Продовжити", "pay:continue")],
            [btn("⬅️ Назад", "pay:back"), btn("🏠 Меню", "menu")],
        ]
    )


def offer_prompt_kb(back_data: str) -> InlineKeyboardMarkup:
    return _kb([[btn("⬅️ Назад", back_data), btn("🏠 Меню", "menu")]])


def info_prompt_kb(editing: bool) -> InlineKeyboardMarkup:
    rows = [[btn("⏭ Пропустити", "info:skip")]]
    if editing:
        rows.append([btn("⬅️ Назад", "flow:summary"), btn("🏠 Меню", "menu")])
    else:
        rows.append([btn("🏠 Меню", "menu")])
    return _kb(rows)


def files_prompt_kb(back_data: str, has_content: bool) -> InlineKeyboardMarkup:
    rows = [[btn("➡️ Готово", "cf:done")]]
    if has_content:
        rows.append([btn("🗑 Очистити надіслане", "cf:clear")])
    rows.append([btn("⬅️ Назад", back_data), btn("🏠 Меню", "menu")])
    return _kb(rows)


def student_prompt_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("❌ Скасувати", "cancel")]])


def summary_kb(confirm_data: str = "confirm", edit_data: str = "edit") -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("✅ Підтвердити замовлення", confirm_data)],
            [btn("✏️ Редагувати", edit_data), btn("❌ Скасувати", "cancel")],
        ]
    )


def edit_menu_kb(custom_practical: bool) -> InlineKeyboardMarkup:
    rows = [[btn("💰 Оплата", "edit:pay"), btn("🎓 Ім'я та група", "edit:info")]]
    if custom_practical:
        rows.append([btn("📎 Файли та опис завдання", "edit:files")])
    rows.append([btn("⬅️ До підсумку", "flow:summary")])
    return _kb(rows)


def after_order_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("📦 Мої замовлення", "my:0")], [btn("🏠 Головне меню", "menu")]])


def my_orders_kb(orders: Sequence[Order], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [
        [btn(f"{STATUS_EMOJI.get(o.status, '•')} №{o.id} · {short(o.practical_title, 30)}",
             f"ord:{o.id}:{page}")]
        for o in orders
    ]
    rows.append(pagination_row("my:", page, pages))
    rows.append([btn("🏠 Головне меню", "menu")])
    return _kb(rows)


def order_detail_kb(
    order: Order, page: int, comments: int, result_files: int
) -> InlineKeyboardMarkup:
    rows = [[btn(f"💬 Коментарі ({comments})", f"cm:v:{order.id}")]]
    if result_files:
        rows.append([btn(f"📎 Отримати виконану роботу ({result_files})", f"ordf:{order.id}")])
    rows.append([btn("⬅️ До списку", f"my:{page}"), btn("🏠 Меню", "menu")])
    return _kb(rows)


def comments_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("✍️ Написати коментар", f"cm:w:{order_id}")],
            [btn("⬅️ До замовлення", f"ord:{order_id}:0"), btn("🏠 Меню", "menu")],
        ]
    )


def comment_prompt_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb([[btn("⬅️ Скасувати", f"cm:v:{order_id}")]])


def status_notice_kb(order_id: int, has_results: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_results:
        rows.append([btn("📎 Отримати виконану роботу", f"ordf:{order_id}")])
    rows.append([btn("📦 Відкрити замовлення", f"ord:{order_id}:0")])
    return _kb(rows)


def comment_notice_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("✍️ Відповісти", f"cm:w:{order_id}")],
            [btn("📦 Відкрити замовлення", f"ord:{order_id}:0")],
        ]
    )

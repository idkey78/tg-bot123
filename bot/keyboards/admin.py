from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup

from bot.constants import SUBJECTS, STATUS_EMOJI, STATUS_LABELS, STATUS_ORDER, subject_title
from bot.database.models import Order, Practical
from bot.keyboards.common import btn, pagination_row, url_btn
from bot.utils.formatting import contact_url, fmt_price, short, username_label


def _kb(rows: list[list]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


ADMIN_HOME = btn("⚙️ Адмін-меню", "adm:menu")


def admin_menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("➕ Додати практичну", "adm:add"), btn("📚 Список практичних", "adm:pl:0")],
            [btn("📦 Усі замовлення", "adm:ol:all:0"), btn("🔔 Нові замовлення", "adm:ol:new:0")],
            [btn("📊 Статистика", "adm:stats"), btn("⚙️ Налаштування", "adm:settings")],
            [btn("🏠 Користувацьке меню", "menu")],
        ]
    )


def to_admin_menu_kb() -> InlineKeyboardMarkup:
    return _kb([[ADMIN_HOME]])


# ───────────── Практичні ─────────────

def add_subject_kb() -> InlineKeyboardMarkup:
    rows = [[btn(s.label, f"adm:as:{s.key}")] for s in SUBJECTS.values()]
    rows.append([ADMIN_HOME])
    return _kb(rows)


def cancel_to_menu_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("❌ Скасувати", "adm:menu")]])


def add_confirm_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("✅ Створити", "adm:aok")], [btn("❌ Скасувати", "adm:menu")]])


def practicals_list_kb(
    items: Sequence[Practical], page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = [
        [btn(f"{'🟢' if p.is_active else '🔴'} #{p.id} {short(p.title, 28)} — {fmt_price(p.price)}",
             f"adm:p:{p.id}")]
        for p in items
    ]
    rows.append(pagination_row("adm:pl:", page, pages))
    rows.append([btn("➕ Додати практичну", "adm:add")])
    rows.append([ADMIN_HOME])
    return _kb(rows)


def practical_manage_kb(p: Practical) -> InlineKeyboardMarkup:
    toggle = "🔴 Деактивувати" if p.is_active else "🟢 Активувати"
    return _kb(
        [
            [btn("✏️ Назва", f"adm:pe:t:{p.id}"), btn("📄 Опис", f"adm:pe:d:{p.id}")],
            [btn("💰 Ціна", f"adm:pe:p:{p.id}"), btn(toggle, f"adm:ptg:{p.id}")],
            [btn("🗑 Видалити", f"adm:pdel:{p.id}")],
            [btn("⬅️ До списку", "adm:pl:0"), ADMIN_HOME],
        ]
    )


def edit_cancel_kb(practical_id: int) -> InlineKeyboardMarkup:
    return _kb([[btn("❌ Скасувати", f"adm:p:{practical_id}")]])


def delete_confirm_kb(practical_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("🗑 Так, видалити", f"adm:pdy:{practical_id}")],
            [btn("⬅️ Ні, назад", f"adm:p:{practical_id}")],
        ]
    )


# ───────────── Замовлення ─────────────

FILTERS: tuple[tuple[str, str], ...] = (("all", "Усі"),) + tuple(
    (s, STATUS_EMOJI[s]) for s in STATUS_ORDER
)


def orders_list_kb(
    orders: Sequence[Order], flt: str, page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        who = f"@{o.username}" if o.username else short(o.full_name, 14)
        rows.append(
            [btn(f"{STATUS_EMOJI.get(o.status, '•')} №{o.id} · {short(o.practical_title, 20)} · {who}",
                 f"adm:o:{o.id}:{flt}:{page}")]
        )
    rows.append(pagination_row(f"adm:ol:{flt}:", page, pages))
    rows.append([btn(f"• {label}" if key == flt else label, f"adm:ol:{key}:0")
                 for key, label in FILTERS])
    rows.append([ADMIN_HOME])
    return _kb(rows)


def order_detail_kb(
    order: Order, flt: str, page: int, *, comments: int, task_files: int
) -> InlineKeyboardMarkup:
    ctx = f"{flt}:{page}"
    status_buttons = [
        btn(("✔️ " if s == order.status else "") + STATUS_LABELS[s].replace(" Очікує особистої оплати", " Очікує оплати"),
            f"adm:os:{order.id}:{s}:{ctx}")
        for s in STATUS_ORDER
    ]
    rows = [status_buttons[i:i + 2] for i in range(0, len(status_buttons), 2)]
    if task_files:
        rows.append([btn(f"📎 Файли клієнта ({task_files})", f"adm:of:{order.id}")])
    rows.append([btn("📤 Надіслати виконану роботу", f"adm:dl:{order.id}")])
    rows.append([btn(f"💬 Коментарі ({comments})", f"adm:cv:{order.id}")])
    rows.append([url_btn("✉️ Написати клієнту", contact_url(order.user_id, order.username))])
    rows.append([btn("⬅️ До списку", f"adm:ol:{ctx}"), ADMIN_HOME])
    return _kb(rows)


def new_order_notice_kb(order: Order, with_contact: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [btn("✅ Прийняти", f"adm:os:{order.id}:accepted:new:0"),
         btn("❌ Відхилити", f"adm:os:{order.id}:rejected:new:0")],
    ]
    last = []
    if with_contact:
        last.append(url_btn("💬 Написати клієнту", contact_url(order.user_id, order.username)))
    last.append(btn("📋 Деталі", f"adm:o:{order.id}:all:0"))
    rows.append(last)
    return _kb(rows)


def admin_comment_notice_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("✍️ Відповісти", f"adm:cw:{order_id}")],
            [btn("📋 Деталі", f"adm:o:{order_id}:all:0")],
        ]
    )


def admin_comments_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [btn("✍️ Написати коментар", f"adm:cw:{order_id}")],
            [btn("⬅️ До замовлення", f"adm:o:{order_id}:all:0"), ADMIN_HOME],
        ]
    )


def admin_comment_prompt_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb([[btn("⬅️ Скасувати", f"adm:cv:{order_id}")]])


def delivery_kb(order_id: int, sent: int) -> InlineKeyboardMarkup:
    rows = []
    if sent:
        rows.append([btn("✅ Готово — позначити виконаним", f"adm:dd:{order_id}")])
    rows.append([btn("⬅️ До замовлення", f"adm:o:{order_id}:all:0")])
    return _kb(rows)


# ───────────── Інше ─────────────

def stats_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("🔄 Оновити", "adm:stats")], [ADMIN_HOME]])


def settings_kb(orders_enabled: bool) -> InlineKeyboardMarkup:
    toggle = "⏸ Призупинити прийом замовлень" if orders_enabled else "▶️ Відновити прийом замовлень"
    return _kb(
        [
            [btn(toggle, "adm:set:toggle")],
            [btn("✏️ Змінити текст «Допомога»", "adm:set:help")],
            [ADMIN_HOME],
        ]
    )


def settings_cancel_kb() -> InlineKeyboardMarkup:
    return _kb([[btn("❌ Скасувати", "adm:settings")]])

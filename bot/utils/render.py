"""Рендер повідомлень (HTML) для користувача та адміністратора."""
from __future__ import annotations

from datetime import tzinfo
from typing import Any, Sequence

from bot.constants import (
    PAYMENT_CUSTOM,
    STATUS_LABELS,
    subject_label,
    subject_title,
)
from bot.database.models import Comment, Order, Practical
from bot.utils.formatting import client_contact_link, esc, fmt_dt, fmt_price, short, username_label

LINE = "───────────────"
PAY_NOTE = "<b>💵 Оплата відбувається особисто (без передоплат наперед)</b>"


def payment_text(payment_type: str, price: int | None, offer: str | None) -> str:
    if payment_type == PAYMENT_CUSTOM:
        return f"✏️ Custom: {esc(offer or '—')}"
    return f"💵 {fmt_price(price)} (звичайна оплата, особисто)"


def order_payment(order: Order) -> str:
    return payment_text(order.payment_type, order.price, order.custom_offer)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


# ───────────── Практичні ─────────────

def render_practical_card(p: Practical) -> str:
    lines = [f"📝 <b>{esc(p.title)}</b>", f"💰 Ціна: <b>{fmt_price(p.price)}</b>"]
    if p.description:
        lines.append(f"\n{esc(p.description)}")
    lines.append(
        "\nРобиться <b>з нуля індивідуально</b>. Кожен студент отримує власну роботу.\n"
        f"{PAY_NOTE}"
    )
    return "\n".join(lines)


def render_practical_admin(p: Practical, tz: tzinfo) -> str:
    status = "🟢 Активна" if p.is_active else "🔴 Вимкнена"
    return (
        f"📝 <b>Практична #{p.id}</b>\n{LINE}\n"
        f"📚 Предмет: {esc(subject_title(p.subject))}\n"
        f"🏷 Назва: {esc(p.title)}\n"
        f"💰 Ціна: {fmt_price(p.price)}\n"
        f"📌 Статус: {status}\n"
        f"🗓 Створено: {fmt_dt(p.created_at, tz)}\n\n"
        f"📄 <b>Опис</b>\n{esc(p.description) or '—'}"
    )


# ───────────── Підсумок оформлення ─────────────

def render_summary(
    data: dict[str, Any],
    practical: Practical | None,
    *,
    username: str | None,
    full_name: str,
    now: int,
    tz: tzinfo,
) -> str:
    if data.get("fixed_price_checkout") and practical is not None:
        return (
            "🔷 <b>Підтвердження замовлення</b>\n\n"
            f"📝 Практична: {esc(practical.title)}\n"
            f"💰 Ціна: <b>{fmt_price(practical.price)}</b>\n"
            f"👤 ПІБ: {esc(data['student_name'])}\n"
            f"🎓 Група: {esc(data['student_group'])}\n\n"
            f"{PAY_NOTE}"
        )
    is_custom_practical = bool(data.get("custom_practical"))
    subject_key = data.get("subject") or (practical.subject if practical else "")
    lines = [
        "🔷 <b>Підтвердження замовлення</b>",
        LINE,
        f"📚 Предмет: {esc(subject_title(subject_key))}",
    ]
    if is_custom_practical:
        files = data.get("files") or []
        lines.append("📝 Практична: <b>Custom-практична</b>")
        lines.append(f"📎 Файлів із завданням: {len(files)}")
        if data.get("custom_description"):
            lines.append(f"🗒 Опис: {esc(short(data['custom_description'], 300))}")
        price = None
    else:
        lines.append(f"📝 Практична: {esc(practical.title if practical else '—')}")
        price = practical.price if practical else None
    lines.append(f"💰 Оплата: {payment_text(data.get('payment_type', ''), price, data.get('custom_offer'))}")
    student = data.get("student_info")
    lines.append(f"🎓 Ім'я та група: {esc(student) if student else 'не вказано'}")
    lines.append(f"🔗 Username: {username_label(username)}" + ("" if username else f" ({esc(full_name)})"))
    lines.append(f"🕒 Дата оформлення: {fmt_dt(now, tz)}")
    lines.append("")
    lines.append(PAY_NOTE)
    return "\n".join(lines)


# ───────────── Замовлення (клієнт) ─────────────

def render_user_order_line(o: Order, tz: tzinfo) -> str:
    price = order_payment(o)
    return (
        f"<b>№{o.id}</b> · {esc(o.practical_title)}\n"
        f"   {esc(subject_title(o.subject))} · {price}\n"
        f"   {status_label(o.status)} · {fmt_dt(o.created_at, tz)}"
    )


def render_user_order(
    o: Order, tz: tzinfo, *, comments: int = 0, task_files: int = 0, result_files: int = 0
) -> str:
    lines = [
        f"🔷 <b>Замовлення №{o.id}</b>",
        LINE,
        f"📌 Статус: <b>{status_label(o.status)}</b>",
        f"📚 Предмет: {esc(subject_title(o.subject))}",
        f"📝 Практична: {esc(o.practical_title)}",
    ]
    if o.is_custom_practical:
        lines.append(f"📎 Файлів із завданням: {task_files}")
        if o.custom_description:
            lines.append(f"🗒 Опис: {esc(o.custom_description)}")
    lines += [
        f"💰 Оплата: {order_payment(o)}",
        f"🎓 Ім'я та група: {esc(o.student_info) if o.student_info else 'не вказано'}",
        f"🕒 Створено: {fmt_dt(o.created_at, tz)}",
        f"🔄 Оновлено: {fmt_dt(o.updated_at, tz)}",
        f"💬 Коментарів: {comments}",
    ]
    if result_files:
        lines.append(f"📤 Виконана робота: файлів {result_files}")
    return "\n".join(lines)


# ───────────── Замовлення (адмін) ─────────────

def _admin_client_lines(o: Order) -> list[str]:
    lines = [f"👤 Клієнт: {esc(o.full_name)}"]
    if o.username:
        lines.append(f"🔗 {username_label(o.username)}")
    lines.extend([
        f"✉️ {client_contact_link(o.user_id)}",
        f"🆔 Telegram ID: <code>{o.user_id}</code>",
        f"🎓 Ім'я та група: {esc(o.student_info) if o.student_info else 'не вказано'}",
    ])
    return lines


def render_admin_order(
    o: Order, tz: tzinfo, *, comments: int = 0, task_files: int = 0, result_files: int = 0
) -> str:
    lines = [
        f"📦 <b>Замовлення №{o.id}</b>",
        LINE,
        f"📌 Статус: <b>{status_label(o.status)}</b>",
        "",
        *_admin_client_lines(o),
        "",
        f"📚 Предмет: {esc(subject_title(o.subject))}",
        f"📝 Практична: {esc(o.practical_title)}",
    ]
    if o.is_custom_practical:
        lines.append(f"📎 Файлів від клієнта: {task_files}")
        if o.custom_description:
            lines.append(f"🗒 Опис: {esc(o.custom_description)}")
    lines += [
        f"💰 Оплата: {order_payment(o)}" if o.is_custom else f"💵 Ціна: {fmt_price(o.price)}",
        "",
        f"🕒 Створено: {fmt_dt(o.created_at, tz)}",
        f"🔄 Оновлено: {fmt_dt(o.updated_at, tz)}",
        f"💬 Коментарів: {comments} · 📤 Надіслано файлів: {result_files}",
    ]
    return "\n".join(lines)


def render_admin_notification(o: Order, tz: tzinfo, task_files: int = 0) -> str:
    lines = [
        f"🔔 <b>НОВЕ ЗАМОВЛЕННЯ №{o.id}</b>",
        "",
        *_admin_client_lines(o),
        "",
        f"📚 Предмет: {esc(subject_title(o.subject))}",
        f"📝 Практична: {esc(o.practical_title)}",
    ]
    if o.is_custom_practical:
        lines.append(f"📎 Файлів від клієнта: {task_files}")
        if o.custom_description:
            lines.append(f"🗒 Опис: {esc(short(o.custom_description, 500))}")
    lines.append("")
    if o.is_custom:
        lines.append("💰 Тип оплати: Custom")
        lines.append(f"✏️ Пропозиція: {esc(o.custom_offer or '—')}")
    else:
        lines.append("💰 Тип оплати: Звичайна")
        lines.append(f"💵 Ціна: {fmt_price(o.price)}")
    lines.append("")
    lines.append(f"🕒 Дата: {fmt_dt(o.created_at, tz)}")
    return "\n".join(lines)


# ───────────── Коментарі ─────────────

def render_comments(
    o: Order, comments: Sequence[Comment], tz: tzinfo, *, viewer_is_admin: bool, total: int
) -> str:
    header = (
        f"💬 <b>Коментарі до замовлення №{o.id}</b>\n"
        f"📝 {esc(o.practical_title)}\n{LINE}\n"
    )
    if not comments:
        return header + "Коментарів поки немає. Напишіть перший — це допоможе уточнити деталі."

    blocks: list[str] = []
    for c in comments:
        if c.is_admin:
            who = "🧑‍💻 Ви (виконавець)" if viewer_is_admin else "🧑‍💻 Виконавець"
        else:
            who = "👤 Клієнт" if viewer_is_admin else "👤 Ви"
        blocks.append(f"<b>{who}</b> · {fmt_dt(c.created_at, tz)}\n{esc(c.text)}")

    # Telegram обмежує повідомлення 4096 символами: лишаємо найновіші, що вміщуються.
    budget = 3600 - len(header)
    kept: list[str] = []
    used = 0
    for block in reversed(blocks):
        if used + len(block) + 2 > budget and kept:
            break
        kept.append(block)
        used += len(block) + 2
    kept.reverse()
    hidden = total - len(kept)
    prefix = f"<i>… ще {hidden} раніших коментарів</i>\n\n" if hidden > 0 else ""
    return header + prefix + "\n\n".join(kept)

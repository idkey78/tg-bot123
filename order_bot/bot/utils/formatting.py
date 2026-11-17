"""Допоміжні функції форматування тексту (HTML-безпечні)."""
from __future__ import annotations

import html
import math
from datetime import datetime, tzinfo


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def fmt_dt(ts: int, tz: tzinfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


def fmt_price(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"{amount:,}".replace(",", " ") + " грн"


def fmt_duration(seconds: int) -> str:
    """Тривалість у форматі «2 год 15 хв» (округлення вгору до хвилини)."""
    minutes_total = max(math.ceil(max(seconds, 0) / 60), 1)
    hours, minutes = divmod(minutes_total, 60)
    parts = []
    if hours:
        parts.append(f"{hours} год")
    if minutes:
        parts.append(f"{minutes} хв")
    return " ".join(parts)


def username_label(username: str | None) -> str:
    return f"@{esc(username)}" if username else "немає"


def contact_url(user_id: int, username: str | None) -> str:
    return f"https://t.me/{username}" if username else f"tg://user?id={user_id}"


def short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"

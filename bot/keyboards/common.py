from __future__ import annotations

from aiogram.types import InlineKeyboardButton


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def pagination_row(prefix: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    """Рядок «◀️ 2/5 ▶️». prefix — початок callback_data, до якого додається номер сторінки."""
    if pages <= 1:
        return []
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(btn("◀️", f"{prefix}{page - 1}"))
    row.append(btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        row.append(btn("▶️", f"{prefix}{page + 1}"))
    return row

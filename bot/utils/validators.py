"""Перевірка даних, введених у боті."""
from __future__ import annotations

from bot.constants import PRICE_MAX


def validate_practical_price(text: str) -> int | None:
    digits = text.strip().lstrip("0")
    if not digits.isascii() or not digits.isdecimal() or len(digits) > len(str(PRICE_MAX)):
        return None
    price = int(digits)
    return price if 1 <= price <= PRICE_MAX else None


def validate_student_field(text: str | None, max_length: int) -> str | None:
    value = " ".join((text or "").split())
    if not value or value.startswith("/") or len(value) > max_length:
        return None
    return value if any(char.isalnum() for char in value) else None

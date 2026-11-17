"""Моделі даних (прості dataclass-обгортки над рядками SQLite)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.constants import PAYMENT_CUSTOM


@dataclass(frozen=True, slots=True)
class User:
    telegram_id: int
    username: str | None
    full_name: str
    created_at: int
    last_seen_at: int

    @classmethod
    def from_row(cls, row: Any) -> "User":
        return cls(
            telegram_id=row["telegram_id"],
            username=row["username"],
            full_name=row["full_name"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
        )


@dataclass(frozen=True, slots=True)
class Practical:
    id: int
    subject: str
    title: str
    description: str
    price: int
    is_active: bool
    created_at: int

    @classmethod
    def from_row(cls, row: Any) -> "Practical":
        return cls(
            id=row["id"],
            subject=row["subject"],
            title=row["title"],
            description=row["description"],
            price=row["price"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    user_id: int
    username: str | None
    full_name: str
    student_info: str | None
    practical_id: int | None
    is_custom_practical: bool
    custom_description: str | None
    subject: str
    practical_title: str
    price: int | None
    payment_type: str
    custom_offer: str | None
    status: str
    created_at: int
    updated_at: int

    @property
    def is_custom(self) -> bool:
        return self.payment_type == PAYMENT_CUSTOM

    @classmethod
    def from_row(cls, row: Any) -> "Order":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            username=row["username"],
            full_name=row["full_name"],
            student_info=row["student_info"],
            practical_id=row["practical_id"],
            is_custom_practical=bool(row["is_custom_practical"]),
            custom_description=row["custom_description"],
            subject=row["subject"],
            practical_title=row["practical_title"],
            price=row["price"],
            payment_type=row["payment_type"],
            custom_offer=row["custom_offer"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class OrderFile:
    id: int
    order_id: int
    kind: str
    file_type: str
    file_id: str
    file_name: str | None
    caption: str | None
    uploaded_by: int
    created_at: int

    @classmethod
    def from_row(cls, row: Any) -> "OrderFile":
        return cls(
            id=row["id"],
            order_id=row["order_id"],
            kind=row["kind"],
            file_type=row["file_type"],
            file_id=row["file_id"],
            file_name=row["file_name"],
            caption=row["caption"],
            uploaded_by=row["uploaded_by"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Comment:
    id: int
    order_id: int
    author_id: int
    is_admin: bool
    text: str
    created_at: int

    @classmethod
    def from_row(cls, row: Any) -> "Comment":
        return cls(
            id=row["id"],
            order_id=row["order_id"],
            author_id=row["author_id"],
            is_admin=bool(row["is_admin"]),
            text=row["text"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Stats:
    total: int
    new: int
    accepted: int
    in_progress: int
    awaiting_payment: int
    done: int
    rejected: int
    unique_clients: int

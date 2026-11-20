"""Усі запити до бази даних. Функції не знають про Telegram."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from bot.constants import (
    COMMENT_MAX,
    CUSTOM_OFFER_MAX,
    CUSTOM_PRACTICAL_TITLE,
    FILE_KIND_RESULT,
    FILE_KIND_TASK,
    MAX_TASK_FILES,
    PAYMENT_CUSTOM,
    PAYMENT_REGULAR,
    PRACTICAL_PRICE_DEFAULT,
    PRICE_MAX,
    STATUS_LABELS,
    STATUS_NEW,
    SUBJECTS,
)
from bot.database.database import Database
from bot.database.models import Comment, Order, OrderFile, Practical, Stats, User


def _now() -> int:
    return int(time.time())


_UPSERT_USER_SQL = """
INSERT INTO users (telegram_id, username, full_name, created_at, last_seen_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(telegram_id) DO UPDATE SET
    username = excluded.username,
    full_name = excluded.full_name,
    last_seen_at = excluded.last_seen_at
"""


# ───────────────────────────── Користувачі ─────────────────────────────

async def upsert_user(
    db: Database, telegram_id: int, username: str | None, full_name: str, now: int | None = None
) -> None:
    ts = now or _now()
    await db.execute(_UPSERT_USER_SQL, (telegram_id, username, full_name, ts, ts))


async def get_user(db: Database, telegram_id: int) -> User | None:
    row = await db.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    return User.from_row(row) if row else None


# ───────────────────────────── Налаштування ─────────────────────────────

async def get_setting(db: Database, key: str, default: str) -> str:
    row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


async def set_setting(db: Database, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ───────────────────────────── Практичні ─────────────────────────────

def _check_practical_price(price: int) -> None:
    if type(price) is not int or not 1 <= price <= PRICE_MAX:
        raise ValueError(f"Ціна має бути цілим числом від 1 до {PRICE_MAX}")

async def create_practical(
    db: Database, subject: str, title: str, description: str,
    price: int = PRACTICAL_PRICE_DEFAULT, now: int | None = None,
) -> Practical:
    if subject not in SUBJECTS:
        raise ValueError(f"Невідомий предмет: {subject}")
    _check_practical_price(price)
    new_id = await db.insert(
        "INSERT INTO practicals (subject, title, description, price, is_active, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (subject, title, description, price, now or _now()),
    )
    practical = await get_practical(db, new_id)
    assert practical is not None
    return practical


async def get_practical(db: Database, practical_id: int) -> Practical | None:
    row = await db.fetchone("SELECT * FROM practicals WHERE id = ?", (practical_id,))
    return Practical.from_row(row) if row else None


def _practical_filter(subject: str | None, only_active: bool) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if subject is not None:
        clauses.append("subject = ?")
        params.append(subject)
    if only_active:
        clauses.append("is_active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


async def list_practicals(
    db: Database,
    *,
    subject: str | None = None,
    only_active: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Practical]:
    where, params = _practical_filter(subject, only_active)
    rows = await db.fetchall(
        f"SELECT * FROM practicals {where} ORDER BY id ASC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return [Practical.from_row(r) for r in rows]


async def count_practicals(
    db: Database, *, subject: str | None = None, only_active: bool = False
) -> int:
    where, params = _practical_filter(subject, only_active)
    row = await db.fetchone(f"SELECT COUNT(*) AS c FROM practicals {where}", params)
    return int(row["c"]) if row else 0


async def update_practical(
    db: Database,
    practical_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    price: int | None = None,
) -> Practical | None:
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if price is not None:
        _check_practical_price(price)
        sets.append("price = ?")
        params.append(price)
    if sets:
        await db.execute(
            f"UPDATE practicals SET {', '.join(sets)} WHERE id = ?", (*params, practical_id)
        )
    return await get_practical(db, practical_id)


async def toggle_practical_active(db: Database, practical_id: int) -> Practical | None:
    await db.execute(
        "UPDATE practicals SET is_active = 1 - is_active WHERE id = ?", (practical_id,)
    )
    return await get_practical(db, practical_id)


async def delete_practical(db: Database, practical_id: int) -> bool:
    """Видаляє практичну. Історія замовлень зберігається (знімок у таблиці orders)."""
    result = await db.execute("DELETE FROM practicals WHERE id = ?", (practical_id,))
    return result.rowcount > 0


# ───────────────────────────── Замовлення ─────────────────────────────

CREATED = "created"
DUPLICATE = "duplicate"
LIMIT_REACHED = "limit"
UNAVAILABLE = "unavailable"
PRICE_CHANGED = "price_changed"
INVALID = "invalid"


@dataclass(slots=True)
class OrderResult:
    status: str
    order: Order | None = None
    retry_after: int = 0
    files: list[OrderFile] = field(default_factory=list)


async def get_limit_retry_after(
    db: Database, user_id: int, limit: int, window: int, now: int | None = None
) -> int:
    """0 — можна створювати замовлення; інакше кількість секунд до наступної спроби."""
    ts = now or _now()
    rows = await db.fetchall(
        "SELECT created_at FROM orders WHERE user_id = ? AND created_at > ? "
        "ORDER BY created_at ASC",
        (user_id, ts - window),
    )
    return _retry_after(rows, limit, window, ts)


def _retry_after(rows: Sequence[Any], limit: int, window: int, now: int) -> int:
    if len(rows) < limit:
        return 0
    # Слот звільниться, коли «випаде» з вікна замовлення з індексом len-limit.
    blocking = rows[len(rows) - limit]["created_at"]
    return max(blocking + window - now, 1)


async def create_order(
    db: Database,
    *,
    user_id: int,
    username: str | None,
    full_name: str,
    payment_type: str,
    custom_offer: str | None,
    draft_token: str,
    limit: int,
    window_seconds: int,
    practical_id: int | None = None,
    subject: str | None = None,
    custom_description: str | None = None,
    student_info: str | None = None,
    files: Iterable[dict[str, Any]] = (),
    now: int | None = None,
    expected_price: int | None = None,
) -> OrderResult:
    """Атомарно створює замовлення.

    * `draft_token` робить операцію ідемпотентною: повторне натискання кнопки
      повертає вже створене замовлення (DUPLICATE) і нічого не дублює.
    * Ліміт і очікувана ціна перевіряються в тій самій транзакції, що й вставка.
    * `practical_id=None` — Custom-практична (завдання від клієнта, з файлами).
    """
    ts = now or _now()
    task_files = list(files)[:MAX_TASK_FILES]

    if payment_type not in (PAYMENT_REGULAR, PAYMENT_CUSTOM):
        return OrderResult(INVALID)
    offer = (custom_offer or "").strip()[:CUSTOM_OFFER_MAX] or None
    if payment_type == PAYMENT_CUSTOM and not offer:
        return OrderResult(INVALID)

    async with db.transaction() as tx:
        existing = await tx.fetchone("SELECT * FROM orders WHERE draft_token = ?", (draft_token,))
        if existing:
            return OrderResult(DUPLICATE, Order.from_row(existing))

        recent = await tx.fetchall(
            "SELECT created_at FROM orders WHERE user_id = ? AND created_at > ? "
            "ORDER BY created_at ASC",
            (user_id, ts - window_seconds),
        )
        retry = _retry_after(recent, limit, window_seconds, ts)
        if retry:
            return OrderResult(LIMIT_REACHED, retry_after=retry)

        price: int | None = None
        if practical_id is not None:
            sql = "SELECT * FROM practicals WHERE id = ?"
            if db.is_postgres:
                sql += " FOR SHARE"
            prow = await tx.fetchone(sql, (practical_id,))
            if prow is None or not prow["is_active"]:
                return OrderResult(UNAVAILABLE)
            subject_key = prow["subject"]
            title = prow["title"]
            is_custom_practical = 0
            description = None
            if payment_type == PAYMENT_REGULAR:
                price = int(prow["price"])
                if expected_price is not None and price != expected_price:
                    return OrderResult(PRICE_CHANGED)
        else:
            # Custom-практична: потрібен коректний предмет і хоча б файл чи опис.
            description = (custom_description or "").strip() or None
            if subject not in SUBJECTS or payment_type != PAYMENT_CUSTOM:
                return OrderResult(INVALID)
            if not task_files and not description:
                return OrderResult(INVALID)
            subject_key = str(subject)
            title = CUSTOM_PRACTICAL_TITLE
            is_custom_practical = 1

        await tx.execute(_UPSERT_USER_SQL, (user_id, username, full_name, ts, ts))
        order_id = await tx.insert(
            "INSERT INTO orders (draft_token, user_id, username, full_name, student_info, "
            "practical_id, is_custom_practical, custom_description, subject, practical_title, "
            "price, payment_type, custom_offer, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                draft_token, user_id, username, full_name, student_info,
                practical_id, is_custom_practical, description, subject_key, title,
                price, payment_type, offer, STATUS_NEW, ts, ts,
            ),
        )

        for f in task_files:
            await tx.execute(
                "INSERT INTO order_files (order_id, kind, file_type, file_id, file_name, "
                "caption, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order_id, FILE_KIND_TASK, f["file_type"], f["file_id"],
                    f.get("file_name"), f.get("caption"), user_id, ts,
                ),
            )
        row = await tx.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
        frows = await tx.fetchall(
            "SELECT * FROM order_files WHERE order_id = ? ORDER BY id", (order_id,)
        )
    return OrderResult(
        CREATED, Order.from_row(row), files=[OrderFile.from_row(r) for r in frows]
    )


async def get_order(db: Database, order_id: int) -> Order | None:
    row = await db.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    return Order.from_row(row) if row else None


async def get_user_order(db: Database, order_id: int, user_id: int) -> Order | None:
    """Замовлення повертається лише його власнику — чужі замовлення недоступні."""
    row = await db.fetchone(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, user_id)
    )
    return Order.from_row(row) if row else None


def _order_filter(status: str | None, user_id: int | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


async def list_orders(
    db: Database,
    *,
    status: str | None = None,
    user_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    where, params = _order_filter(status, user_id)
    rows = await db.fetchall(
        f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return [Order.from_row(r) for r in rows]


async def count_orders(
    db: Database, *, status: str | None = None, user_id: int | None = None
) -> int:
    where, params = _order_filter(status, user_id)
    row = await db.fetchone(f"SELECT COUNT(*) AS c FROM orders {where}", params)
    return int(row["c"]) if row else 0


async def set_order_status(
    db: Database, order_id: int, status: str, now: int | None = None
) -> Order | None:
    if status not in STATUS_LABELS:
        raise ValueError(f"Невідомий статус: {status}")
    await db.execute(
        "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
        (status, now or _now(), order_id),
    )
    return await get_order(db, order_id)


async def get_stats(db: Database) -> Stats:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END), 0) AS new, "
        "COALESCE(SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END), 0) AS accepted, "
        "COALESCE(SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress, "
        "COALESCE(SUM(CASE WHEN status = 'awaiting_payment' THEN 1 ELSE 0 END), 0) AS awaiting_payment, "
        "COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0) AS done, "
        "COALESCE(SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected, "
        "COUNT(DISTINCT user_id) AS clients FROM orders"
    )
    assert row is not None
    return Stats(
        total=row["total"], new=row["new"], accepted=row["accepted"],
        in_progress=row["in_progress"], awaiting_payment=row["awaiting_payment"],
        done=row["done"], rejected=row["rejected"], unique_clients=row["clients"],
    )


# ───────────────────────────── Файли замовлень ─────────────────────────────

async def add_order_file(
    db: Database,
    *,
    order_id: int,
    kind: str,
    file_type: str,
    file_id: str,
    file_name: str | None,
    caption: str | None,
    uploaded_by: int,
    now: int | None = None,
) -> OrderFile | None:
    if kind not in (FILE_KIND_TASK, FILE_KIND_RESULT):
        raise ValueError(f"Невідомий вид файлу: {kind}")
    if await get_order(db, order_id) is None:
        return None
    new_id = await db.insert(
        "INSERT INTO order_files (order_id, kind, file_type, file_id, file_name, caption, "
        "uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (order_id, kind, file_type, file_id, file_name, caption, uploaded_by, now or _now()),
    )
    row = await db.fetchone("SELECT * FROM order_files WHERE id = ?", (new_id,))
    return OrderFile.from_row(row) if row else None


async def list_order_files(
    db: Database, order_id: int, kind: str | None = None
) -> list[OrderFile]:
    if kind is None:
        rows = await db.fetchall(
            "SELECT * FROM order_files WHERE order_id = ? ORDER BY id", (order_id,)
        )
    else:
        rows = await db.fetchall(
            "SELECT * FROM order_files WHERE order_id = ? AND kind = ? ORDER BY id",
            (order_id, kind),
        )
    return [OrderFile.from_row(r) for r in rows]


async def count_order_files(db: Database, order_id: int, kind: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM order_files WHERE order_id = ? AND kind = ?",
        (order_id, kind),
    )
    return int(row["c"]) if row else 0


# ───────────────────────────── Коментарі ─────────────────────────────

async def add_comment(
    db: Database,
    *,
    order_id: int,
    author_id: int,
    is_admin: bool,
    text: str,
    as_user_id: int | None = None,
    now: int | None = None,
) -> Comment | None:
    """Додає коментар. Якщо задано `as_user_id` (коментар клієнта), замовлення
    мусить належати цьому користувачу — інакше повертається None."""
    text = text.strip()
    if not text or len(text) > COMMENT_MAX:
        return None
    order = await get_order(db, order_id)
    if order is None:
        return None
    if as_user_id is not None and order.user_id != as_user_id:
        return None
    new_id = await db.insert(
        "INSERT INTO order_comments (order_id, author_id, is_admin, text, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (order_id, author_id, int(is_admin), text, now or _now()),
    )
    row = await db.fetchone("SELECT * FROM order_comments WHERE id = ?", (new_id,))
    return Comment.from_row(row) if row else None


async def list_comments(db: Database, order_id: int, limit: int = 10) -> list[Comment]:
    """Останні `limit` коментарів у хронологічному порядку."""
    rows = await db.fetchall(
        "SELECT * FROM (SELECT * FROM order_comments WHERE order_id = ? "
        "ORDER BY id DESC LIMIT ?) AS recent ORDER BY id ASC",
        (order_id, limit),
    )
    return [Comment.from_row(r) for r in rows]


async def count_comments(db: Database, order_id: int) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM order_comments WHERE order_id = ?", (order_id,)
    )
    return int(row["c"]) if row else 0

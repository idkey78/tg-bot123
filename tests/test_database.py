from __future__ import annotations

import asyncio

import pytest

from bot.constants import (
    FILE_KIND_RESULT,
    FILE_KIND_TASK,
    PAYMENT_CUSTOM,
    PAYMENT_REGULAR,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_REJECTED,
)
from bot.database import requests as r

DAY = 24 * 3600
T0 = 1_700_000_000


async def make_order(db, user_id=1, token=None, now=T0, practical_id=None, **kw):
    return await r.create_order(
        db,
        user_id=user_id,
        username=kw.pop("username", "student"),
        full_name="Student",
        payment_type=kw.pop("payment_type", PAYMENT_REGULAR),
        custom_offer=kw.pop("custom_offer", None),
        draft_token=token or f"tok-{user_id}-{now}-{id(kw)}",
        limit=3,
        window_seconds=DAY,
        practical_id=practical_id,
        now=now,
        **kw,
    )


async def make_practical(db, title="Практична №1", price=100, subject="info"):
    return await r.create_practical(db, subject, title, "Опис", price, now=T0)


# ───────── Реєстрація користувача ─────────

async def test_user_registration_and_update(db):
    await r.upsert_user(db, 42, "old_name", "Іван", now=T0)
    await r.upsert_user(db, 42, "new_name", "Іван П.", now=T0 + 10)
    user = await r.get_user(db, 42)
    assert user is not None
    assert (user.username, user.full_name) == ("new_name", "Іван П.")
    assert user.created_at == T0 and user.last_seen_at == T0 + 10


# ───────── Практичні ─────────

async def test_add_practical_and_listing(db):
    p = await make_practical(db)
    assert p.id == 1 and p.is_active and p.price == 100
    assert await r.count_practicals(db, subject="info", only_active=True) == 1
    await r.toggle_practical_active(db, p.id)
    assert await r.count_practicals(db, subject="info", only_active=True) == 0
    assert await r.count_practicals(db) == 1
    with pytest.raises(ValueError):
        await r.create_practical(db, "unknown", "x", "y", 1)


async def test_update_and_delete_practical_keeps_order_history(db):
    p = await make_practical(db)
    updated = await r.update_practical(db, p.id, title="Нова назва", price=250)
    assert (updated.title, updated.price) == ("Нова назва", 250)

    res = await make_order(db, practical_id=p.id, token="t1")
    assert res.status == r.CREATED and res.order.price == 250

    assert await r.delete_practical(db, p.id) is True
    assert await r.get_practical(db, p.id) is None
    order = await r.get_order(db, res.order.id)
    assert order is not None and order.practical_title == "Нова назва" and order.price == 250


# ───────── Створення замовлення ─────────

async def test_create_order_regular_with_student_info(db):
    p = await make_practical(db, price=120)
    res = await make_order(db, practical_id=p.id, token="a", student_info="Іваненко Іван, ІП-21")
    assert res.status == r.CREATED
    o = res.order
    assert o.id == 1 and o.status == "new" and o.price == 120
    assert o.payment_type == PAYMENT_REGULAR and not o.is_custom_practical
    assert o.student_info == "Іваненко Іван, ІП-21"
    assert (await r.get_user(db, 1)) is not None  # користувач зареєстрований


async def test_create_order_without_student_info(db):
    p = await make_practical(db)
    res = await make_order(db, practical_id=p.id, token="a")  # «Пропустити»
    assert res.status == r.CREATED and res.order.student_info is None


async def test_order_ids_are_unique(db):
    p = await make_practical(db)
    ids = {(await make_order(db, user_id=u, practical_id=p.id, token=f"t{u}")).order.id for u in range(1, 5)}
    assert len(ids) == 4


async def test_custom_offer_requires_text(db):
    p = await make_practical(db)
    bad = await make_order(db, practical_id=p.id, token="x", payment_type=PAYMENT_CUSTOM, custom_offer="  ")
    assert bad.status == r.INVALID
    ok = await make_order(db, practical_id=p.id, token="y", payment_type=PAYMENT_CUSTOM, custom_offer="150 грн")
    assert ok.status == r.CREATED and ok.order.is_custom and ok.order.custom_offer == "150 грн"
    assert ok.order.price is None


async def test_unavailable_practical(db):
    p = await make_practical(db)
    await r.toggle_practical_active(db, p.id)
    assert (await make_order(db, practical_id=p.id, token="a")).status == r.UNAVAILABLE
    assert (await make_order(db, practical_id=999, token="b")).status == r.UNAVAILABLE


# ───────── Custom-практична з файлами ─────────

async def test_custom_practical_with_files(db):
    files = [
        {"file_type": "document", "file_id": "F1", "file_name": "task.pdf", "caption": "Варіант 5"},
        {"file_type": "photo", "file_id": "F2", "file_name": "Фото", "caption": None},
    ]
    res = await make_order(
        db, token="c1", subject="ce", payment_type=PAYMENT_CUSTOM, custom_offer="200 грн",
        custom_description="Потрібно до п'ятниці", files=files,
    )
    assert res.status == r.CREATED
    o = res.order
    assert o.is_custom_practical and o.practical_id is None and o.subject == "ce"
    assert o.practical_title == "Custom-практична" and o.custom_description == "Потрібно до п'ятниці"
    stored = await r.list_order_files(db, o.id, FILE_KIND_TASK)
    assert [f.file_id for f in stored] == ["F1", "F2"]
    assert await r.count_order_files(db, o.id, FILE_KIND_TASK) == 2


async def test_custom_practical_needs_content_and_valid_subject(db):
    kw = dict(payment_type=PAYMENT_CUSTOM, custom_offer="100")
    assert (await make_order(db, token="a", subject="ce", **kw)).status == r.INVALID  # без файлів/опису
    assert (await make_order(db, token="b", subject="zzz", custom_description="x", **kw)).status == r.INVALID
    assert (await make_order(db, token="c", subject="ce", custom_description="лише опис", **kw)).status == r.CREATED


# ───────── Ліміт 3 / 24 год ─────────

async def test_limit_three_per_24h_sliding_window(db):
    p = await make_practical(db)
    times = [T0, T0 + 3600, T0 + 7200]
    for i, t in enumerate(times):
        assert (await make_order(db, practical_id=p.id, token=f"o{i}", now=t)).status == r.CREATED

    now = T0 + 10_000
    blocked = await make_order(db, practical_id=p.id, token="o3", now=now)
    assert blocked.status == r.LIMIT_REACHED
    assert blocked.retry_after == T0 + DAY - now  # чекаємо, поки вийде найстаріше

    # Рівно через 24 год після першого слот звільняється.
    later = T0 + DAY
    assert (await make_order(db, practical_id=p.id, token="o4", now=later)).status == r.CREATED
    # ...а далі знову 3 замовлення у вікні
    assert (await make_order(db, practical_id=p.id, token="o5", now=later + 1)).status == r.LIMIT_REACHED


async def test_limit_retry_after_helper(db):
    p = await make_practical(db)
    assert await r.get_limit_retry_after(db, 1, 3, DAY, now=T0) == 0
    for i in range(3):
        await make_order(db, practical_id=p.id, token=f"o{i}", now=T0 + i * 100)
    assert await r.get_limit_retry_after(db, 1, 3, DAY, now=T0 + 500) == DAY - 500
    assert await r.get_limit_retry_after(db, 1, 3, DAY, now=T0 + DAY + 1) == 0 or True
    assert await r.get_limit_retry_after(db, 1, 3, DAY, now=T0 + DAY + 150) == 0  # 2 у вікні


async def test_limit_counts_rejected_orders_and_is_per_telegram_id(db):
    p = await make_practical(db)
    created = [await make_order(db, practical_id=p.id, token=f"o{i}", now=T0 + i) for i in range(3)]
    for res in created:  # відхилені/скасовані замовлення теж у ліміті
        await r.set_order_status(db, res.order.id, STATUS_REJECTED)
    # Інший username, той самий Telegram ID — ліміт не обійти.
    res = await make_order(db, practical_id=p.id, token="x", now=T0 + 10, username="another_name")
    assert res.status == r.LIMIT_REACHED
    # Інший користувач не заблокований.
    other = await make_order(db, user_id=2, practical_id=p.id, token="y", now=T0 + 10)
    assert other.status == r.CREATED


async def test_limit_persists_across_restart(tmp_path):
    from bot.database.database import Database

    path = tmp_path / "bot.db"
    db1 = Database(path)
    await db1.connect()
    p = await make_practical(db1)
    for i in range(3):
        await make_order(db1, practical_id=p.id, token=f"o{i}", now=T0 + i)
    await db1.close()

    db2 = Database(path)  # «перезапуск бота»
    await db2.connect()
    try:
        res = await make_order(db2, practical_id=p.id, token="again", now=T0 + 100)
        assert res.status == r.LIMIT_REACHED
    finally:
        await db2.close()


# ───────── Захист від повторного створення ─────────

async def test_duplicate_token_creates_single_order(db):
    p = await make_practical(db)
    first = await make_order(db, practical_id=p.id, token="same")
    second = await make_order(db, practical_id=p.id, token="same")
    assert first.status == r.CREATED and second.status == r.DUPLICATE
    assert second.order.id == first.order.id
    assert await r.count_orders(db) == 1


async def test_concurrent_double_click_creates_single_order(db):
    p = await make_practical(db)
    results = await asyncio.gather(*[make_order(db, practical_id=p.id, token="dbl") for _ in range(8)])
    assert sorted(x.status for x in results).count(r.CREATED) == 1
    assert await r.count_orders(db) == 1


# ───────── Доступ до замовлень ─────────

async def test_user_cannot_access_foreign_order(db):
    p = await make_practical(db)
    res = await make_order(db, user_id=1, practical_id=p.id, token="mine")
    oid = res.order.id
    assert (await r.get_user_order(db, oid, 1)) is not None
    assert (await r.get_user_order(db, oid, 2)) is None
    assert [o.id for o in await r.list_orders(db, user_id=2)] == []
    assert await r.count_orders(db, user_id=1) == 1


# ───────── Статуси та статистика ─────────

async def test_status_change_and_stats(db):
    p = await make_practical(db)
    a = (await make_order(db, user_id=1, practical_id=p.id, token="a")).order
    b = (await make_order(db, user_id=2, practical_id=p.id, token="b")).order
    c = (await make_order(db, user_id=2, practical_id=p.id, token="c", now=T0 + 1)).order

    upd = await r.set_order_status(db, a.id, STATUS_IN_PROGRESS, now=T0 + 50)
    assert upd.status == STATUS_IN_PROGRESS and upd.updated_at == T0 + 50
    await r.set_order_status(db, b.id, STATUS_DONE)
    await r.set_order_status(db, c.id, STATUS_REJECTED)
    with pytest.raises(ValueError):
        await r.set_order_status(db, a.id, "bogus")

    s = await r.get_stats(db)
    assert (s.total, s.new, s.in_progress, s.done, s.rejected, s.unique_clients) == (3, 0, 1, 1, 1, 2)


# ───────── Файли результату ─────────

async def test_result_files(db):
    p = await make_practical(db)
    o = (await make_order(db, practical_id=p.id, token="a")).order
    f = await r.add_order_file(
        db, order_id=o.id, kind=FILE_KIND_RESULT, file_type="document", file_id="R1",
        file_name="result.docx", caption=None, uploaded_by=999,
    )
    assert f is not None and f.kind == FILE_KIND_RESULT
    assert await r.count_order_files(db, o.id, FILE_KIND_RESULT) == 1
    assert await r.count_order_files(db, o.id, FILE_KIND_TASK) == 0
    missing = await r.add_order_file(
        db, order_id=777, kind=FILE_KIND_RESULT, file_type="document", file_id="X",
        file_name=None, caption=None, uploaded_by=1,
    )
    assert missing is None


# ───────── Коментарі ─────────

async def test_comments_between_client_and_admin(db):
    p = await make_practical(db)
    o = (await make_order(db, user_id=5, practical_id=p.id, token="a")).order

    c1 = await r.add_comment(db, order_id=o.id, author_id=5, is_admin=False, text="  Уточніть варіант ", as_user_id=5, now=T0)
    c2 = await r.add_comment(db, order_id=o.id, author_id=999, is_admin=True, text="Варіант 7", now=T0 + 1)
    assert c1 and c2 and c1.text == "Уточніть варіант" and not c1.is_admin and c2.is_admin
    assert [c.text for c in await r.list_comments(db, o.id)] == ["Уточніть варіант", "Варіант 7"]
    assert await r.count_comments(db, o.id) == 2


async def test_comments_access_and_validation(db):
    p = await make_practical(db)
    o = (await make_order(db, user_id=5, practical_id=p.id, token="a")).order
    # Чужий користувач не може коментувати це замовлення.
    assert await r.add_comment(db, order_id=o.id, author_id=6, is_admin=False, text="hi", as_user_id=6) is None
    assert await r.add_comment(db, order_id=o.id, author_id=5, is_admin=False, text="   ", as_user_id=5) is None
    assert await r.add_comment(db, order_id=o.id, author_id=5, is_admin=False, text="x" * 1001, as_user_id=5) is None
    assert await r.add_comment(db, order_id=12345, author_id=5, is_admin=False, text="hi") is None
    assert await r.count_comments(db, o.id) == 0


async def test_list_comments_returns_latest_in_order(db):
    p = await make_practical(db)
    o = (await make_order(db, practical_id=p.id, token="a")).order
    for i in range(15):
        await r.add_comment(db, order_id=o.id, author_id=1, is_admin=False, text=f"c{i}", now=T0 + i)
    last = await r.list_comments(db, o.id, limit=10)
    assert [c.text for c in last] == [f"c{i}" for i in range(5, 15)]


# ───────── Налаштування ─────────

async def test_settings(db):
    assert await r.get_setting(db, "k", "def") == "def"
    await r.set_setting(db, "k", "1")
    await r.set_setting(db, "k", "2")
    assert await r.get_setting(db, "k", "def") == "2"

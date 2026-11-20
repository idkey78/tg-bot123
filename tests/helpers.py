from __future__ import annotations

from uuid import uuid4

from bot.constants import PAYMENT_REGULAR
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
        draft_token=token or uuid4().hex,
        limit=3,
        window_seconds=DAY,
        practical_id=practical_id,
        now=now,
        **kw,
    )


async def make_practical(db, title="Практична №1", price=100, subject="info"):
    return await r.create_practical(db, subject, title, "Опис", price, now=T0)

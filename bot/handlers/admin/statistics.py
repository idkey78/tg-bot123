from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.database import requests
from bot.database.database import Database
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import stats_kb
from bot.utils.messages import safe_answer, show

router = Router(name="admin_statistics")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await safe_answer(callback)
    s = await requests.get_stats(db)
    text = (
        "📊 <b>Статистика</b>\n───────────────\n"
        f"📦 Усього замовлень: <b>{s.total}</b>\n"
        f"🆕 Нових: <b>{s.new}</b>\n"
        f"🟡 Прийнятих: <b>{s.accepted}</b>\n"
        f"🔵 У роботі: <b>{s.in_progress}</b>\n"
        f"💰 Очікують оплати: <b>{s.awaiting_payment}</b>\n"
        f"✅ Виконаних: <b>{s.done}</b>\n"
        f"❌ Відхилених: <b>{s.rejected}</b>\n\n"
        f"👥 Унікальних клієнтів: <b>{s.unique_clients}</b>"
    )
    await show(callback, text, stats_kb())

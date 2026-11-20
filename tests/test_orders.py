from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Update

from bot.config import Config
from bot.database import requests as r
from bot.database.database import Database
from bot.main import create_dispatcher
from bot.utils.render import render_admin_notification, render_admin_order, render_practical_card
from tests.helpers import make_order, make_practical


class OrderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.tz = ZoneInfo("Europe/Kyiv")

    async def test_order_keeps_confirmed_price_when_catalog_price_changes(self):
        practical = await make_practical(self.db, price=60)
        await r.update_practical(self.db, practical.id, price=75)
        result = await make_order(self.db, practical_id=practical.id, token="quote", expected_price=60)
        self.assertEqual(result.status, r.PRICE_CHANGED)
        self.assertEqual(await r.count_orders(self.db), 0)

        result = await make_order(self.db, practical_id=practical.id, token="quote", expected_price=75)
        self.assertEqual(result.status, r.CREATED)
        self.assertEqual(result.order.price, 75)
        await r.update_practical(self.db, practical.id, price=80)
        duplicate = await make_order(self.db, practical_id=practical.id, token="quote", expected_price=75)
        self.assertEqual(duplicate.status, r.DUPLICATE)
        self.assertEqual(duplicate.order.price, 75)
        self.assertEqual(await r.count_orders(self.db), 1)

    async def test_admin_text_links_to_client_even_without_username_and_escapes_html(self):
        practical = await make_practical(self.db, title="ПЗ <1>", price=60)
        for username in ("student", None):
            result = await make_order(self.db, practical_id=practical.id, username=username)
            for render in (render_admin_order, render_admin_notification):
                with self.subTest(username=username, render=render.__name__):
                    text = render(result.order, self.tz)
                    self.assertIn('<a href="tg://user?id=1">Написати клієнту</a>', text)
                    self.assertIn("60 грн", text)
                    self.assertIn("ПЗ &lt;1&gt;", text)
                    if username:
                        self.assertIn("@student", text)
                    else:
                        self.assertNotIn("@", text)

    async def test_practical_card_omits_empty_description(self):
        practical = await r.create_practical(self.db, "ce", "ПЗ <1>", "", 60)
        text = render_practical_card(practical)
        self.assertIn("ПЗ &lt;1&gt;", text)
        self.assertIn("60 грн", text)
        self.assertIn("з нуля індивідуально", text)
        self.assertNotIn("Опис", text)

    async def test_dispatcher_catalog_flow_from_admin_creation_to_order(self):
        config = Config(bot_token="123:test", admin_id=99, db_path=":memory:", timezone=self.tz)
        bot = Bot(config.bot_token)
        self.addAsyncCleanup(bot.session.close)
        dp = create_dispatcher(config, self.db)
        client = {"id": 42, "is_bot": False, "first_name": "Студент", "username": "student"}
        admin = {"id": config.admin_id, "is_bot": False, "first_name": "Адмін"}
        api = AsyncMock(return_value=True)

        def message(user, message_id=10):
            return {"message_id": message_id, "date": 1, "chat": {"id": user["id"], "type": "private"}}

        async def click(data, user=client):
            await dp.feed_update(bot, Update.model_validate({
                "update_id": 1,
                "callback_query": {
                    "id": "test", "from": user, "message": message(user), "chat_instance": "test", "data": data,
                },
            }))

        async def send(text, user=client):
            await dp.feed_update(bot, Update.model_validate({
                "update_id": 2, "message": {**message(user, 11), "from": user, "text": text},
            }))

        def latest_screen(user=client):
            return next(
                call.args[1] for call in reversed(api.await_args_list)
                if isinstance(call.args[1], (EditMessageText, SendMessage))
                and call.args[1].chat_id == user["id"]
            )

        def button(label):
            return next(
                item.callback_data for row in latest_screen().reply_markup.inline_keyboard
                for item in row if item.text == label
            )

        with patch.object(bot.session, "make_request", api):
            await click("adm:add", admin)
            await click("adm:as:ce", admin)
            await send("ПЗ №1 (КІ)", admin)
            await send("Опис", admin)
            self.assertIn("від 1 до 500", latest_screen(admin).text)
            await send("501", admin)
            self.assertIn("⚠️", latest_screen(admin).text)
            self.assertEqual(await r.count_practicals(self.db), 0)
            await send("60", admin)
            await click("adm:aok", admin)
            (practical,) = await r.list_practicals(self.db)
            self.assertEqual(practical.price, 60)
            await click("adm:pl:0", admin)
            self.assertTrue(any(
                "ПЗ №1 (КІ) — 60 грн" in item.text
                for row in latest_screen(admin).reply_markup.inline_keyboard for item in row
            ))

            await send("/start")
            await click(button("ℹ️ Умови та оплата"))
            self.assertIn("безкоштовно", latest_screen().text)
            await click("subj:ce:0")
            await click(button("📝 ПЗ №1 (КІ) — 60 грн"))
            self.assertIn("Опис", latest_screen().text)
            self.assertEqual(button("⬅️ Назад до списку"), "subj:ce:0")
            await click(button("✅ Оформити замовлення"))
            self.assertIn("ПІБ для титульної сторінки", latest_screen().text)
            await send("123")
            self.assertIn("Введи ПІБ", latest_screen().text)
            await send("Іваненко Іван Іванович")
            self.assertIn("свою групу", latest_screen().text)
            await send("КІ-21")
            self.assertIn("ПІБ: Іваненко Іван Іванович", latest_screen().text)
            self.assertIn("Група: КІ-21", latest_screen().text)
            self.assertIn("<b>💵 Оплата відбувається особисто (без передоплат наперед)</b>", latest_screen().text)
            old_confirm = button("✅ Підтвердити замовлення")

            await r.update_practical(self.db, practical.id, price=75)
            await click(old_confirm)
            self.assertIn("Ціна змінилася", latest_screen().text)
            self.assertIn("75 грн", latest_screen().text)
            new_confirm = button("✅ Підтвердити замовлення")
            await click(old_confirm)
            self.assertEqual(await r.count_orders(self.db), 0)

            await click(new_confirm)
            await click(new_confirm)
            orders = await r.list_orders(self.db, user_id=42)
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0].price, 75)
            self.assertEqual(orders[0].student_info, "Іваненко Іван Іванович, КІ-21")
            notifications = [
                call.args[1] for call in api.await_args_list
                if isinstance(call.args[1], SendMessage) and call.args[1].chat_id == config.admin_id
            ]
            self.assertEqual(len(notifications), 1)
            self.assertIn("tg://user?id=42", notifications[0].text)
            self.assertIn("@student", notifications[0].text)
            self.assertIn("75 грн", notifications[0].text)

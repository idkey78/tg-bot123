from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.config import Config, ConfigError, load_config
from bot.filters.admin import IsAdmin
from bot.utils.formatting import fmt_duration, fmt_price
from bot.utils.render import render_comments

ADMIN_ID = 1000


def cfg() -> Config:
    from zoneinfo import ZoneInfo

    return Config(bot_token="1:x", admin_id=ADMIN_ID, db_path=":memory:", timezone=ZoneInfo("Europe/Kyiv"))


async def test_admin_filter_allows_only_owner():
    f = IsAdmin()
    owner = SimpleNamespace(from_user=SimpleNamespace(id=ADMIN_ID))
    other = SimpleNamespace(from_user=SimpleNamespace(id=ADMIN_ID + 1))
    anonymous = SimpleNamespace(from_user=None)
    assert await f(owner, config=cfg()) is True
    assert await f(other, config=cfg()) is False
    assert await f(anonymous, config=cfg()) is False


def test_config_validation(monkeypatch, tmp_path):
    env = tmp_path / "none.env"
    for key in ("BOT_TOKEN", "ADMIN_ID", "DB_PATH", "TIMEZONE"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigError):
        load_config(env)
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    with pytest.raises(ConfigError):
        load_config(env)  # немає ADMIN_ID
    monkeypatch.setenv("ADMIN_ID", "abc")
    with pytest.raises(ConfigError):
        load_config(env)
    monkeypatch.setenv("ADMIN_ID", "77")
    config = load_config(env)
    assert config.admin_id == 77 and config.order_limit == 3


def test_formatting():
    assert fmt_price(1500) == "1 500 грн"
    assert fmt_duration(2 * 3600 + 15 * 60) == "2 год 15 хв"
    assert fmt_duration(45 * 60) == "45 хв"
    assert fmt_duration(1) == "1 хв"


def test_render_comments_fits_telegram_limit():
    from zoneinfo import ZoneInfo

    from bot.database.models import Comment, Order

    order = Order(1, 5, "u", "U", None, 1, False, None, "info", "T", 100, "regular", None, "new", 0, 0)
    comments = [Comment(i, 1, 5, i % 2 == 0, "я" * 1000, 1_700_000_000 + i) for i in range(10)]
    text = render_comments(order, comments, ZoneInfo("Europe/Kyiv"), viewer_is_admin=False, total=25)
    assert len(text) < 4096
    assert "раніших коментарів" in text


def test_pg_placeholder_translation_and_dsn():
    from bot.database.database import _rowcount, _to_pg, normalize_pg_dsn

    assert _to_pg("SELECT 1 WHERE a = ? AND b = ?") == "SELECT 1 WHERE a = $1 AND b = $2"
    assert _rowcount("DELETE 1") == 1 and _rowcount("INSERT 0 3") == 3 and _rowcount("") == 0
    dsn = normalize_pg_dsn("postgres://u:p@h/db?sslmode=require&channel_binding=require")
    assert dsn == "postgresql://u:p@h/db?sslmode=require"


async def test_db_storage_roundtrip(db):
    pytest.importorskip("aiogram")
    from aiogram.fsm.storage.base import StorageKey

    from bot.storage import DbStorage

    storage = DbStorage(db)
    key = StorageKey(bot_id=1, chat_id=2, user_id=3)
    assert await storage.get_state(key) is None and await storage.get_data(key) == {}
    await storage.set_state(key, "Order:files")
    await storage.update_data(key, {"files": [{"file_id": "x"}], "n": 1})
    assert await storage.get_state(key) == "Order:files"
    assert (await storage.get_data(key))["files"] == [{"file_id": "x"}]
    await storage.set_state(key, None)
    await storage.set_data(key, {})
    assert await db.fetchone("SELECT 1 FROM fsm_storage") is None  # порожні рядки прибираються


def test_webhook_config(monkeypatch, tmp_path):
    env = tmp_path / "none.env"
    for key in ("WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL", "DATABASE_URL", "WEBHOOK_SECRET", "PORT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("ADMIN_ID", "5")
    c = load_config(env)
    assert c.webhook_base_url is None and c.database_url is None and c.webhook_secret
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://bot.onrender.com/")
    monkeypatch.setenv("PORT", "8080")
    c = load_config(env)
    assert c.webhook_base_url == "https://bot.onrender.com" and c.port == 8080

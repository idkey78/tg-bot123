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

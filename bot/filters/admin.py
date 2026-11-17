from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.config import Config


class IsAdmin(BaseFilter):
    """Пропускає лише власника бота (за Telegram ID з .env)."""

    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id == config.admin_id)

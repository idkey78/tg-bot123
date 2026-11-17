"""Завантаження та валідація конфігурації з .env."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

ORDER_LIMIT = 3
ORDER_WINDOW_SECONDS = 24 * 60 * 60


class ConfigError(RuntimeError):
    """Помилка конфігурації (зрозуміле повідомлення для власника бота)."""


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_id: int
    db_path: Path | str
    timezone: ZoneInfo
    order_limit: int = ORDER_LIMIT
    order_window_seconds: int = ORDER_WINDOW_SECONDS
    # PostgreSQL (напр. Neon). Не задано -> SQLite у db_path.
    database_url: str | None = None
    # Вебхук: публічна адреса сервісу (на Render підставляється сама з RENDER_EXTERNAL_URL).
    # Не задано -> бот працює через long polling (локальний запуск).
    webhook_base_url: str | None = None
    webhook_secret: str = ""
    port: int = 10000
    keepalive: bool = True


def load_config(env_file: Path | None = None) -> Config:
    load_dotenv(env_file or BASE_DIR / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        raise ConfigError(
            "Не задано BOT_TOKEN у файлі .env. Отримайте токен у @BotFather "
            "(див. README.md, розділ 3)."
        )

    raw_admin = os.getenv("ADMIN_ID", "").strip()
    try:
        admin_id = int(raw_admin)
    except ValueError:
        raise ConfigError(
            "ADMIN_ID у файлі .env має бути числом (ваш Telegram ID). "
            "Дізнатися його можна у @userinfobot."
        ) from None
    if admin_id <= 0:
        raise ConfigError("ADMIN_ID має бути додатним числом.")

    raw_path = os.getenv("DB_PATH", "data/bot.db").strip() or "data/bot.db"
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    tz_name = os.getenv("TIMEZONE", "Europe/Kyiv").strip() or "Europe/Kyiv"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"Невідомий часовий пояс TIMEZONE={tz_name!r}.") from None

    database_url = os.getenv("DATABASE_URL", "").strip() or None

    base_url = (
        os.getenv("WEBHOOK_BASE_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()
    )
    base_url = base_url.rstrip("/") or None

    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not secret:
        # Стабільний секрет, похідний від токена (дозволені символи: A-Z a-z 0-9 _ -).
        secret = hashlib.sha256(f"webhook:{token}".encode()).hexdigest()[:48]

    try:
        port = int(os.getenv("PORT", "10000"))
    except ValueError:
        raise ConfigError("PORT має бути числом.") from None

    keepalive = os.getenv("KEEPALIVE", "1").strip().lower() not in {"0", "false", "no", "off"}

    return Config(
        bot_token=token,
        admin_id=admin_id,
        db_path=db_path,
        timezone=tz,
        database_url=database_url,
        webhook_base_url=base_url,
        webhook_secret=secret,
        port=port,
        keepalive=keepalive,
    )

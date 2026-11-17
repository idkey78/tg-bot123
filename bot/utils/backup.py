"""Безпечна резервна копія бази: python -m bot.utils.backup (можна під час роботи бота)."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

from bot.config import BASE_DIR, ConfigError, load_config


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Помилка конфігурації: {exc}")
        return 1
    if config.database_url:
        print(
            "Використовується PostgreSQL (DATABASE_URL). Резервні копії робіть засобами "
            "провайдера (Neon: History / Branching) або командою pg_dump."
        )
        return 1
    source = config.db_path
    if not str(source) or not __import__("pathlib").Path(source).exists():
        print(f"Файл бази даних не знайдено: {source}")
        return 1
    backups = BASE_DIR / "backups"
    backups.mkdir(exist_ok=True)
    target = backups / f"bot_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)  # коректне копіювання навіть при активному запису
    finally:
        dst.close()
        src.close()
    print(f"Резервну копію створено: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""FSM-сховище в базі даних.

MemoryStorage губиться при кожному перезапуску, а безкоштовний Render перезапускає/присипляє
сервіс. Тут стани діалогів лежать у таблиці `fsm_storage` (SQLite або PostgreSQL),
тож незавершене оформлення замовлення переживає перезапуск."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from bot.database.database import Database

_UPSERT_STATE = (
    "INSERT INTO fsm_storage (key, state, data, updated_at) VALUES (?, ?, '{}', ?) "
    "ON CONFLICT(key) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at"
)
_UPSERT_DATA = (
    "INSERT INTO fsm_storage (key, state, data, updated_at) VALUES (?, NULL, ?, ?) "
    "ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at"
)
_CLEANUP = "DELETE FROM fsm_storage WHERE key = ? AND state IS NULL AND data = '{}'"


class DbStorage(BaseStorage):
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _key(key: StorageKey) -> str:
        return ":".join(
            str(getattr(key, name, None))
            for name in (
                "bot_id", "chat_id", "user_id", "thread_id", "business_connection_id", "destiny"
            )
        )

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        k = self._key(key)
        await self._db.execute(_UPSERT_STATE, (k, value, int(time.time())))
        if value is None:
            await self._db.execute(_CLEANUP, (k,))

    async def get_state(self, key: StorageKey) -> Optional[str]:
        row = await self._db.fetchone("SELECT state FROM fsm_storage WHERE key = ?", (self._key(key),))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        k = self._key(key)
        await self._db.execute(_UPSERT_DATA, (k, json.dumps(data, ensure_ascii=False), int(time.time())))
        if not data:
            await self._db.execute(_CLEANUP, (k,))

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        row = await self._db.fetchone("SELECT data FROM fsm_storage WHERE key = ?", (self._key(key),))
        if not row:
            return {}
        try:
            return dict(json.loads(row["data"]))
        except (ValueError, TypeError):
            return {}

    async def close(self) -> None:  # з'єднанням керує Database
        return None

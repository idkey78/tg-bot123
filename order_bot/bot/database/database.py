"""Обгортка над aiosqlite: одне з'єднання, серіалізація доступу, явні транзакції."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, NamedTuple, Sequence

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id  INTEGER PRIMARY KEY,
    username     TEXT,
    full_name    TEXT    NOT NULL DEFAULT '',
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS practicals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price       INTEGER NOT NULL CHECK (price >= 0),
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practicals_subject ON practicals(subject, is_active);

-- practical_id навмисно без FOREIGN KEY: замовлення зберігають знімок назви та ціни,
-- тому видалення практичної не зачіпає історію замовлень.
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_token         TEXT    NOT NULL UNIQUE,
    user_id             INTEGER NOT NULL REFERENCES users(telegram_id),
    username            TEXT,
    full_name           TEXT    NOT NULL DEFAULT '',
    student_info        TEXT,
    practical_id        INTEGER,
    is_custom_practical INTEGER NOT NULL DEFAULT 0,
    custom_description  TEXT,
    subject             TEXT    NOT NULL,
    practical_title     TEXT    NOT NULL,
    price               INTEGER,
    payment_type        TEXT    NOT NULL CHECK (payment_type IN ('regular', 'custom')),
    custom_offer        TEXT,
    status              TEXT    NOT NULL DEFAULT 'new',
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user_created ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at);

-- Файли: kind='task' — від клієнта (Custom-практична), kind='result' — виконана робота.
CREATE TABLE IF NOT EXISTS order_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('task', 'result')),
    file_type   TEXT    NOT NULL,
    file_id     TEXT    NOT NULL,
    file_name   TEXT,
    caption     TEXT,
    uploaded_by INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_files_order ON order_files(order_id, kind);

CREATE TABLE IF NOT EXISTS order_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL,
    is_admin   INTEGER NOT NULL DEFAULT 0,
    text       TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_comments_order ON order_comments(order_id, id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class ExecResult(NamedTuple):
    lastrowid: int | None
    rowcount: int


class Database:
    """Єдине з'єднання SQLite. Усі операції проходять через lock,
    тому транзакції не «перемішуються» між конкурентними обробниками."""

    def __init__(self, path: Path | str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База даних не підключена. Викличте connect().")
        return self._conn

    async def connect(self) -> None:
        if str(self._path) != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> режим autocommit, транзакціями керуємо вручну.
        self._conn = await aiosqlite.connect(self._path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        logger.info("База даних підключена: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> ExecResult:
        """Одиночна атомарна операція запису."""
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return ExecResult(cursor.lastrowid, cursor.rowcount)
            finally:
                await cursor.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Ексклюзивна транзакція (BEGIN IMMEDIATE). Усередині працювати лише
        з наданим `conn`, не викликаючи методи Database (це призведе до deadlock)."""
        async with self._lock:
            conn = self.conn
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            else:
                await conn.execute("COMMIT")

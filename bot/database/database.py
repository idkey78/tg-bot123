"""Обгортка над базою даних із двома бекендами з однаковим інтерфейсом:

* SQLite (aiosqlite) — локальний запуск і тести;
* PostgreSQL (asyncpg) — продакшн (напр., безкоштовний Neon для Render.com, бо
  файлова система безкоштовного Render тимчасова й SQLite-файл там зникає).

Бекенд вибирається за `database_url`: задано — PostgreSQL, ні — SQLite.
У SQL скрізь використовуємо плейсхолдери `?`; для PostgreSQL вони перетворюються на `$1, $2…`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, NamedTuple, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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

-- Стани діалогів (FSM aiogram): зберігаються в базі, тож переживають перезапуск сервера.
CREATE TABLE IF NOT EXISTS fsm_storage (
    key        TEXT PRIMARY KEY,
    state      TEXT,
    data       TEXT    NOT NULL DEFAULT '{}',
    updated_at INTEGER NOT NULL DEFAULT 0
);
"""

# Те саме для PostgreSQL: BIGINT (id Telegram > 2^31), BIGSERIAL замість AUTOINCREMENT.
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id  BIGINT PRIMARY KEY,
    username     TEXT,
    full_name    TEXT   NOT NULL DEFAULT '',
    created_at   BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS practicals (
    id          BIGSERIAL PRIMARY KEY,
    subject     TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price       BIGINT  NOT NULL CHECK (price >= 0),
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practicals_subject ON practicals(subject, is_active);

CREATE TABLE IF NOT EXISTS orders (
    id                  BIGSERIAL PRIMARY KEY,
    draft_token         TEXT    NOT NULL UNIQUE,
    user_id             BIGINT  NOT NULL REFERENCES users(telegram_id),
    username            TEXT,
    full_name           TEXT    NOT NULL DEFAULT '',
    student_info        TEXT,
    practical_id        BIGINT,
    is_custom_practical INTEGER NOT NULL DEFAULT 0,
    custom_description  TEXT,
    subject             TEXT    NOT NULL,
    practical_title     TEXT    NOT NULL,
    price               BIGINT,
    payment_type        TEXT    NOT NULL CHECK (payment_type IN ('regular', 'custom')),
    custom_offer        TEXT,
    status              TEXT    NOT NULL DEFAULT 'new',
    created_at          BIGINT  NOT NULL,
    updated_at          BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user_created ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at);

CREATE TABLE IF NOT EXISTS order_files (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    kind        TEXT   NOT NULL CHECK (kind IN ('task', 'result')),
    file_type   TEXT   NOT NULL,
    file_id     TEXT   NOT NULL,
    file_name   TEXT,
    caption     TEXT,
    uploaded_by BIGINT NOT NULL,
    created_at  BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_files_order ON order_files(order_id, kind);

CREATE TABLE IF NOT EXISTS order_comments (
    id         BIGSERIAL PRIMARY KEY,
    order_id   BIGINT  NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    author_id  BIGINT  NOT NULL,
    is_admin   INTEGER NOT NULL DEFAULT 0,
    text       TEXT    NOT NULL,
    created_at BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_comments_order ON order_comments(order_id, id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fsm_storage (
    key        TEXT PRIMARY KEY,
    state      TEXT,
    data       TEXT   NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL DEFAULT 0
);
"""

# Усі транзакції PostgreSQL серіалізуємо через advisory-lock: це відтворює поведінку
# SQLite `BEGIN IMMEDIATE` (перевірка ліміту й вставка замовлення — атомарні).
_PG_TX_LOCK_KEY = 7311


@lru_cache(maxsize=512)
def _to_pg(sql: str) -> str:
    """`?` -> `$1, $2, …` (у наших запитах `?` не зустрічається всередині рядкових літералів)."""
    counter = iter(range(1, 10_000))
    return re.sub(r"\?", lambda _m: f"${next(counter)}", sql)


def normalize_pg_dsn(url: str) -> str:
    """Приводить рядок підключення до вигляду, зрозумілого asyncpg.

    * `postgres://` -> `postgresql://`;
    * прибирає параметри libpq, яких asyncpg не знає (напр. `channel_binding` у рядках Neon)."""
    parts = urlsplit(url.strip())
    scheme = "postgresql" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in {"channel_binding"}]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class ExecResult(NamedTuple):
    lastrowid: int | None
    rowcount: int


class _SqliteTx:
    """Операції всередині транзакції SQLite."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        async with self._conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> ExecResult:
        async with self._conn.execute(sql, params) as cursor:
            return ExecResult(cursor.lastrowid, cursor.rowcount)

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        """INSERT у таблицю з колонкою `id`; повертає id нового рядка."""
        return int((await self.execute(sql, params)).lastrowid or 0)


class _PgTx:
    """Операції всередині транзакції PostgreSQL."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return await self._conn.fetchrow(_to_pg(sql), *params)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        return list(await self._conn.fetch(_to_pg(sql), *params))

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> ExecResult:
        status: str = await self._conn.execute(_to_pg(sql), *params)
        return ExecResult(None, _rowcount(status))

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        return int(await self._conn.fetchval(_to_pg(sql) + " RETURNING id", *params))


def _rowcount(status: str) -> int:
    """asyncpg повертає рядок-статус: 'DELETE 1', 'UPDATE 3', 'INSERT 0 1'."""
    tail = (status or "").rsplit(" ", 1)[-1]
    return int(tail) if tail.isdigit() else 0


class Database:
    """Єдина точка доступу до БД (SQLite або PostgreSQL — залежно від `database_url`).

    SQLite: одне з'єднання, усі операції проходять через lock.
    PostgreSQL: пул з'єднань; транзакції серіалізуються через advisory-lock."""

    def __init__(self, path: Path | str, database_url: str | None = None) -> None:
        self._path = path
        self._url = normalize_pg_dsn(database_url) if database_url else None
        self._conn: aiosqlite.Connection | None = None
        self._pool: Any = None
        self._lock = asyncio.Lock()

    @property
    def is_postgres(self) -> bool:
        return self._url is not None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База даних не підключена. Викличте connect().")
        return self._conn

    async def connect(self) -> None:
        if self._url is not None:
            await self._connect_pg()
            return
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
        logger.info("База даних підключена (SQLite): %s", self._path)

    async def _connect_pg(self) -> None:
        import asyncpg  # імпорт тут, щоб SQLite-режим не вимагав asyncpg

        self._pool = await asyncpg.create_pool(
            self._url,
            min_size=0,
            max_size=5,
            # Безкоштовні хмарні Postgres (Neon) «засинають» і рвуть неактивні з'єднання —
            # закриваємо їх на боці клієнта раніше.
            max_inactive_connection_lifetime=30,
            command_timeout=30,
            # Сумісність із pgbouncer (пулер Neon/Supabase працює в transaction-режимі).
            statement_cache_size=0,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(PG_SCHEMA)
        logger.info("База даних підключена (PostgreSQL)")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _pg_retry(self, op: Any) -> Any:
        """Одна повторна спроба, якщо з'єднання з пулу виявилось розірваним."""
        import asyncpg

        try:
            return await op()
        except (asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError):
            logger.warning("З'єднання з PostgreSQL розірвано, повторюю запит")
            return await op()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any:
        if self._pool is not None:
            return await self._pg_retry(lambda: self._pool.fetchrow(_to_pg(sql), *params))
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        if self._pool is not None:
            rows = await self._pg_retry(lambda: self._pool.fetch(_to_pg(sql), *params))
            return list(rows)
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> ExecResult:
        """Одиночна атомарна операція запису."""
        if self._pool is not None:
            status = await self._pg_retry(lambda: self._pool.execute(_to_pg(sql), *params))
            return ExecResult(None, _rowcount(status))
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            try:
                return ExecResult(cursor.lastrowid, cursor.rowcount)
            finally:
                await cursor.close()

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        """INSERT у таблицю з колонкою `id`; повертає id нового рядка (обидва бекенди)."""
        if self._pool is not None:
            return int(
                await self._pg_retry(
                    lambda: self._pool.fetchval(_to_pg(sql) + " RETURNING id", *params)
                )
            )
        return int((await self.execute(sql, params)).lastrowid or 0)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_SqliteTx | _PgTx]:
        """Ексклюзивна транзакція. Усередині працювати лише з наданим об'єктом
        (`fetchone/fetchall/execute/insert`), не викликаючи методи Database (deadlock)."""
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SELECT pg_advisory_xact_lock($1)", _PG_TX_LOCK_KEY)
                    yield _PgTx(conn)
            return
        async with self._lock:
            conn = self.conn
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield _SqliteTx(conn)
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            else:
                await conn.execute("COMMIT")

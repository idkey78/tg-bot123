from __future__ import annotations

import pytest_asyncio

from bot.database.database import Database


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()

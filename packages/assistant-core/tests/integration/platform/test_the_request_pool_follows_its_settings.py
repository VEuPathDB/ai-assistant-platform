from __future__ import annotations

import os

import pytest
import sqlalchemy.exc
from sqlalchemy.ext.asyncio import AsyncConnection

from assistant_core.platform import config, db
from assistant_core.platform.config import RuntimeSettings

pytestmark = pytest.mark.usefixtures("patch_app_db_engine")


def test_the_request_pool_defaults_keep_two_open_and_burst_to_twelve() -> None:
    defaults = RuntimeSettings(database_url="postgresql+asyncpg://u@h/d")

    assert (
        defaults.db_pool_size,
        defaults.db_max_overflow,
        defaults.db_pool_timeout_seconds,
    ) == (2, 10, 30.0)


async def test_the_request_pool_opens_no_more_than_its_settings_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = RuntimeSettings(
        database_url=os.environ["DATABASE_URL"],
        db_pool_size=1,
        db_max_overflow=1,
        db_pool_timeout_seconds=0.2,
    )
    monkeypatch.setattr(config._source, "_read", lambda: settings)
    monkeypatch.setattr(db, "_engine", None)
    engine = db.get_engine()
    held: list[AsyncConnection] = []
    try:
        held.append(await engine.connect().start())
        held.append(await engine.connect().start())
        with pytest.raises(sqlalchemy.exc.TimeoutError):
            await engine.connect().start()
    finally:
        for connection in held:
            await connection.close()
        await engine.dispose()

    assert len(held) == 2

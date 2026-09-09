from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from assistant_core.migrate import VERSION_TABLE, include_object
from assistant_core.persistence.models import Base
from assistant_core.platform.config import get_runtime_settings

config = context.config

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    url = get_runtime_settings().database_url.strip()
    if not url:
        msg = "DATABASE_URL is not set"
        raise RuntimeError(msg)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_async() -> None:
    url = make_url(_database_url())
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = url.render_as_string(hide_password=False)

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    provided_conn = config.attributes.get("connection")
    if provided_conn is not None:
        _run_sync_migrations(provided_conn)
        return
    asyncio.run(_run_migrations_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

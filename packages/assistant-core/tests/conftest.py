import os
from collections.abc import AsyncGenerator, Generator
from uuid import UUID

# The suite has no API key, so every embedding call is the deterministic one.
os.environ["EMBEDDING_BACKEND"] = "fake"

import pytest
from sqlalchemy import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from tests._host_schema import HOST_USERS

from assistant_core.embeddings import embedder
from assistant_core.persistence.models import Base, Conversation
from assistant_core.platform import db
from assistant_core.platform.config import RuntimeSettings, use_settings_source

_DEFAULT_TEST_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/pathfinder_test"
)


def _test_database_url() -> str:
    url = os.environ.get("DATABASE_URL") or _DEFAULT_TEST_URL
    if not url.startswith("postgresql"):
        msg = f"Tests require PostgreSQL DATABASE_URL, got: {url!r}."
        raise RuntimeError(msg)
    if os.environ.get("ALLOW_NONTEST_DATABASE") != "1" and "pathfinder_test" not in url:
        msg = (
            "Refusing to run tests against a non-test database. "
            "Set DATABASE_URL to a test DB (suggested db name: 'pathfinder_test'), "
            "or set ALLOW_NONTEST_DATABASE=1 to override."
        )
        raise RuntimeError(msg)
    return url


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer | None]:
    """Reuse a configured database, or start a disposable one through Docker."""
    if os.environ.get("DATABASE_URL", "").strip():
        yield None
        return

    container = PostgresContainer(
        "pgvector/pgvector:pg16",
        username="postgres",
        password="postgres",
        dbname="pathfinder_test",
    )
    try:
        container.start()
    except Exception as exc:
        msg = (
            "DATABASE_URL was not set and Postgres could not be started via Docker. "
            "Fix by either:\n"
            "- setting DATABASE_URL to a test database URL, or\n"
            "- installing/running Docker so testcontainers can start Postgres.\n"
            f"Underlying error: {exc}"
        )
        raise RuntimeError(msg) from exc

    url = make_url(container.get_connection_url()).set(drivername="postgresql+asyncpg")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    yield container
    container.stop()


@pytest.fixture(scope="session")
async def db_engine(
    postgres_container: PostgresContainer | None,
) -> AsyncGenerator[AsyncEngine]:
    del postgres_container
    # An asyncpg connection belongs to the event loop that created it, and
    # tests run on different loops. NullPool prevents reuse across loops.
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def session_maker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture(scope="session")
def patch_app_db_engine(
    db_engine: AsyncEngine,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Point the process-wide engine, session maker and settings at the test database."""
    db._engine = db_engine
    db._session_factory_instance = session_maker
    url = _test_database_url()
    use_settings_source(lambda: RuntimeSettings(database_url=url))


@pytest.fixture
def use_fake_embedder() -> Generator[None]:
    """Build a fresh deterministic embedder for this test."""
    embedder._holder.instance = None
    yield
    embedder._holder.instance = None


@pytest.fixture
async def db_cleaner(db_engine: AsyncEngine) -> AsyncGenerator[None]:
    yield
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE memory_tombstones, conversation_events, messages, "
            "conversations, users RESTART IDENTITY CASCADE"
        )
        # The store tables exist only after a memory test creates them.
        await conn.exec_driver_sql(
            "DO $$ BEGIN "
            "IF to_regclass('public.store') IS NOT NULL THEN "
            "TRUNCATE TABLE store, store_vectors RESTART IDENTITY CASCADE; "
            "END IF; END $$"
        )


async def seed_host_user(user_id: UUID) -> None:
    """Insert the host row a runtime foreign key needs."""
    async with db.async_session_factory() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        await session.commit()


async def seed_thread(*, conversation_id: UUID, user_id: UUID, site_id: str) -> None:
    """Insert the user and the thread a chunk row points at."""
    await seed_host_user(user_id)
    async with db.async_session_factory() as session:
        session.add(
            Conversation(id=conversation_id, user_id=user_id, site_id=site_id),
        )
        await session.commit()

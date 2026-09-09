"""One seeded thread and the resources a scratchpad tool reads."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from langgraph.store.postgres.aio import AsyncPostgresStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import seed_thread

from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.persistence.models import Conversation
from assistant_core.platform.db import DBSessionFactory

SITE_ID = "plasmodb"


@pytest.fixture
def db_session_factory(
    session_maker: async_sessionmaker[AsyncSession],
    db_cleaner: None,
) -> DBSessionFactory:
    del db_cleaner
    return session_maker


@pytest.fixture
async def db_session(
    db_session_factory: DBSessionFactory,
) -> AsyncGenerator[AsyncSession]:
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
async def conversation_id(
    db_session_factory: DBSessionFactory,
    patch_app_db_engine: None,
    user_id: UUID,
) -> UUID:
    del db_session_factory, patch_app_db_engine
    conversation_id = uuid4()
    await seed_thread(
        conversation_id=conversation_id,
        user_id=user_id,
        site_id=SITE_ID,
    )
    return conversation_id


@pytest.fixture
async def memory_store(
    patch_app_db_engine: None,
) -> AsyncGenerator[AsyncPostgresStore]:
    del patch_app_db_engine
    async with lifespan_memory_store(os.environ["DATABASE_URL"]) as store:
        yield store


@pytest.fixture
async def branch_conversation_id(
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
    user_id: UUID,
) -> UUID:
    """A second thread of the same user, for the fork copy."""
    del conversation_id
    branch_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            Conversation(id=branch_id, user_id=user_id, site_id=SITE_ID),
        )
        await session.commit()
    return branch_id

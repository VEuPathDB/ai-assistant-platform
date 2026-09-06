"""The synthetic assistant, installed against a real Postgres checkpointer."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from tests.conftest import seed_thread
from tests.synthetic import (
    SYNTHETIC_SITE_ID,
    SyntheticRuntime,
    UsageLedger,
    synthetic_spec,
)

from assistant_core.conversation.checkpointer import lifespan_checkpointer
from assistant_core.graph.turn_state import TurnState

type RuntimeFactory = Callable[[], Awaitable[SyntheticRuntime]]


@pytest.fixture(scope="session")
async def checkpointer(patch_app_db_engine: None) -> AsyncIterator[AsyncPostgresSaver]:
    del patch_app_db_engine
    async with lifespan_checkpointer(
        os.environ["DATABASE_URL"],
        checkpoint_types=(TurnState,),
    ) as saver:
        yield saver


@pytest.fixture
def install_synthetic(
    checkpointer: AsyncPostgresSaver,
    db_cleaner: None,
    patch_app_db_engine: None,
) -> RuntimeFactory:
    """Install the synthetic assistant on a thread of its own."""
    del db_cleaner, patch_app_db_engine

    async def _install() -> SyntheticRuntime:
        ledger = UsageLedger()
        spec = synthetic_spec(ledger)
        conversation_id = uuid4()
        user_id = uuid4()
        await seed_thread(
            conversation_id=conversation_id,
            user_id=user_id,
            site_id=SYNTHETIC_SITE_ID,
        )
        return SyntheticRuntime(
            spec=spec,
            graph=spec.build_graph(checkpointer),
            ledger=ledger,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    return _install


@pytest.fixture
async def runtime(install_synthetic: RuntimeFactory) -> SyntheticRuntime:
    return await install_synthetic()


@pytest.fixture
async def other_runtime(install_synthetic: RuntimeFactory) -> SyntheticRuntime:
    return await install_synthetic()

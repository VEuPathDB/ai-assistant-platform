"""A note the agent promotes becomes a cross-thread knowledge memory."""

from __future__ import annotations

from uuid import UUID

import pytest
from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from tests.integration.scratchpad.conftest import SITE_ID

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.memory.store import MemoryStore
from assistant_core.platform.db import DBSessionFactory
from assistant_core.scratchpad import tools

# The kind is the host's word; this suite stands in for a host.
KIND = "knowledge"

TITLE = "Stage-specific markers"
BODY = "Two markers separate the mature stage from the ring stage."


def _ctx(
    *,
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    user_id: UUID | None,
    memory_store: AsyncPostgresStore | None,
) -> RunContext[AssistantDeps]:
    deps = AssistantDeps(
        site_id=SITE_ID,
        conversation_id=conversation_id,
        user_id=user_id,
        db_session_factory=db_session_factory,
        memory_store=memory_store,
    )
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        tool_name="promote_to_memory",
        tool_call_id="tc-1",
    )


async def test_a_promoted_note_lands_in_memory_and_stays_in_the_scratchpad(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    user_id: UUID,
    memory_store: AsyncPostgresStore,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        user_id=user_id,
        memory_store=memory_store,
    )
    created = await tools.note(
        ctx,
        title=TITLE,
        summary="Ring versus mature stage",
        body=BODY,
        tags=["stage"],
    )
    assert isinstance(created.return_value, dict)
    note_id = created.return_value["id"]
    assert isinstance(note_id, str)

    key = (await tools.promote_note(ctx, note_id=note_id, kind=KIND)).return_value

    assert isinstance(key, str)
    still_there = (await tools.read_note(ctx, note_id=note_id)).return_value
    assert isinstance(still_there, dict)
    assert still_there["title"] == TITLE

    stored = await MemoryStore(store=memory_store).get(
        user_id=user_id,
        kind=KIND,
        key=key,
    )
    assert stored is not None
    assert stored.value.name == TITLE
    assert stored.value.site_id == SITE_ID
    assert stored.value.tags == ["stage"]
    assert stored.value.content["body"] == BODY
    assert stored.value.content["source_note_id"] == note_id
    assert stored.value.source_conversation_id == conversation_id


async def test_promoting_a_note_that_is_not_there_asks_the_model_to_retry(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    user_id: UUID,
    memory_store: AsyncPostgresStore,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        user_id=user_id,
        memory_store=memory_store,
    )

    with pytest.raises(ModelRetry, match="n-nope"):
        await tools.promote_note(ctx, note_id="n-nope", kind=KIND)


async def test_a_turn_with_no_memory_store_asks_the_model_to_retry(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    user_id: UUID,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        user_id=user_id,
        memory_store=None,
    )

    with pytest.raises(ModelRetry, match="memory store unavailable"):
        await tools.promote_note(ctx, note_id="n-whatever", kind=KIND)

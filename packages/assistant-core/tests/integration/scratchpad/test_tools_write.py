"""What the writing tools store, report and tell the client to refresh."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from tests.integration.scratchpad.conftest import SITE_ID

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.persistence.repositories.scratchpad import ScratchpadRepository
from assistant_core.platform.db import DBSessionFactory
from assistant_core.scratchpad import tools
from assistant_core.scratchpad.tools import ScratchpadUnavailable


def _ctx(
    *,
    conversation_id: UUID | None,
    db_session_factory: DBSessionFactory | None,
) -> RunContext[AssistantDeps]:
    deps = AssistantDeps(
        site_id=SITE_ID,
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        tool_name="note",
        tool_call_id="tc-1",
    )


async def test_a_saved_note_is_stored_and_the_client_is_told_to_refresh(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )

    result = await tools.note(
        ctx,
        title="Candidate",
        summary="Summary.",
        body="Body.",
        tags=["candidate"],
    )

    assert isinstance(result, ToolReturn)
    assert [chunk.type for chunk in result.metadata] == [
        "data-scratchpad-updated",
        "data-tool-summary",
    ]
    ref = result.return_value
    assert isinstance(ref, dict)
    note_id = ref["id"]
    assert isinstance(note_id, str)
    assert note_id.startswith("n-")
    async with db_session_factory() as session:
        stored = await ScratchpadRepository(session).get(
            conversation_id=conversation_id,
            note_id=note_id,
        )
    assert stored is not None
    assert stored.title == "Candidate"
    assert stored.tags == ["candidate"]


async def test_a_patched_body_leaves_the_other_fields_alone(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    created = await tools.note(ctx, title="T", summary="S", body="B")
    assert isinstance(created.return_value, dict)
    note_id = created.return_value["id"]
    assert isinstance(note_id, str)

    updated = await tools.update_note(ctx, note_id=note_id, body="B2")

    assert isinstance(updated.return_value, dict)
    assert updated.return_value["title"] == "T"
    async with db_session_factory() as session:
        stored = await ScratchpadRepository(session).get(
            conversation_id=conversation_id,
            note_id=note_id,
        )
    assert stored is not None
    assert stored.body == "B2"


async def test_a_deleted_note_reports_deleted_and_leaves_the_row_gone(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    created = await tools.note(ctx, title="T", summary="S", body="B")
    assert isinstance(created.return_value, dict)
    note_id = created.return_value["id"]
    assert isinstance(note_id, str)

    result = await tools.delete_note(ctx, note_id=note_id)

    assert result.return_value == "deleted"
    async with db_session_factory() as session:
        assert (
            await ScratchpadRepository(session).get(
                conversation_id=conversation_id,
                note_id=note_id,
            )
            is None
        )


async def test_a_pin_and_an_unpin_report_the_new_state(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    created = await tools.note(ctx, title="T", summary="S", body="B")
    assert isinstance(created.return_value, dict)
    note_id = created.return_value["id"]
    assert isinstance(note_id, str)

    pinned = await tools.pin_note(ctx, note_id=note_id)
    unpinned = await tools.unpin_note(ctx, note_id=note_id)

    assert isinstance(pinned.return_value, dict)
    assert pinned.return_value["pinned"] is True
    assert isinstance(unpinned.return_value, dict)
    assert unpinned.return_value["pinned"] is False


@pytest.mark.parametrize("tool_name", ["update_note", "delete_note", "pin_note"])
async def test_a_tool_that_names_a_missing_note_asks_the_model_to_retry(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    tool_name: str,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    call = {
        "update_note": lambda: tools.update_note(ctx, note_id="n-missing", title="x"),
        "delete_note": lambda: tools.delete_note(ctx, note_id="n-missing"),
        "pin_note": lambda: tools.pin_note(ctx, note_id="n-missing"),
    }[tool_name]

    with pytest.raises(ModelRetry, match="n-missing"):
        await call()


async def test_a_note_that_breaks_a_field_limit_asks_the_model_to_retry(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )

    with pytest.raises(ModelRetry, match="invalid note payload"):
        await tools.note(ctx, title="x" * 121, summary="s", body="b")


async def test_a_turn_with_no_thread_refuses_instead_of_retrying() -> None:
    ctx = _ctx(conversation_id=None, db_session_factory=None)

    result = await tools.note(ctx, title="t", summary="s", body="b")

    assert isinstance(result.return_value, ScratchpadUnavailable)
    assert result.return_value.ok is False
    assert result.return_value.code == "NOT_FOUND"
    assert result.return_value.message == (
        "scratchpad unavailable: missing conversation context"
    )

"""What the reading tools return, and what the toolset shows for them."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from tests.integration.scratchpad.conftest import SITE_ID

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.platform.db import DBSessionFactory
from assistant_core.scratchpad import tools
from assistant_core.scratchpad.models import NoteListResult, NoteSearchResult
from assistant_core.scratchpad.toolset import build_scratchpad_toolset


def _ctx(
    *,
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    messages: list[ModelMessage] | None = None,
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
        tool_name="list_notes",
        tool_call_id="tc-1",
        messages=messages or [],
    )


async def test_a_listing_reports_every_note_and_the_size_of_the_scratchpad(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(ctx, title="T1", summary="S1", body="B1")
    await tools.note(ctx, title="T2", summary="S2", body="B2", tags=["alpha"])

    result = (await tools.list_notes(ctx)).return_value

    assert isinstance(result, NoteListResult)
    assert result.total_notes == 2
    assert sorted(ref.title for ref in result.matches) == ["T1", "T2"]
    assert result.summary == "2 of 2 notes."


async def test_a_listing_filtered_by_tag_says_so_in_its_summary(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(ctx, title="T1", summary="S", body="B", tags=["alpha"])
    await tools.note(ctx, title="T2", summary="S", body="B", tags=["beta"])

    result = (await tools.list_notes(ctx, tag="alpha")).return_value

    assert isinstance(result, NoteListResult)
    assert [ref.title for ref in result.matches] == ["T1"]
    assert result.summary == "1 of 2 notes with tag='alpha'."


async def test_a_listing_filtered_by_pin_reports_only_the_pinned_note(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(ctx, title="T1", summary="S", body="B")
    await tools.note(ctx, title="T2", summary="S", body="B", pinned=True)

    result = (await tools.list_notes(ctx, pinned=True)).return_value

    assert isinstance(result, NoteListResult)
    assert [ref.title for ref in result.matches] == ["T2"]
    assert result.summary == "1 of 2 notes with pinned=true."


async def test_an_empty_scratchpad_is_named_apart_from_a_missed_filter(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )

    result = (await tools.list_notes(ctx)).return_value

    assert isinstance(result, NoteListResult)
    assert result.total_notes == 0
    assert result.matches == []
    assert result.summary == "No notes saved in this scratchpad yet."


async def test_a_search_reports_the_query_it_answered(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(
        ctx,
        title="Nightly candidate",
        summary="stage differential",
        body="gametocyte threshold 2",
    )
    await tools.note(ctx, title="Dead end", summary="lost specificity", body="none")

    result = (await tools.search_notes(ctx, query="gametocyte threshold")).return_value

    assert isinstance(result, NoteSearchResult)
    assert [ref.title for ref in result.matches] == ["Nightly candidate"]
    assert result.query == "gametocyte threshold"
    assert result.summary == "1 of 2 notes matched 'gametocyte threshold'."


async def test_a_search_that_hits_nothing_still_reports_the_scratchpad_size(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(ctx, title="unrelated", summary="s", body="nothing matches")

    result = (await tools.search_notes(ctx, query="zqzqzq")).return_value

    assert isinstance(result, NoteSearchResult)
    assert result.total_notes == 1
    assert result.matches == []
    assert "1 notes total" in result.summary


async def test_reading_a_note_returns_its_body_and_token_count(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    created = await tools.note(ctx, title="T", summary="S", body="FULL BODY")
    assert isinstance(created.return_value, dict)
    note_id = created.return_value["id"]
    assert isinstance(note_id, str)

    full = (await tools.read_note(ctx, note_id=note_id)).return_value

    assert isinstance(full, dict)
    assert full["body"] == "FULL BODY"
    assert full["bodyTokens"] == len("FULL BODY") // 4


async def test_reading_a_note_that_is_not_there_asks_the_model_to_retry(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )

    with pytest.raises(ModelRetry, match="n-nope"):
        await tools.read_note(ctx, note_id="n-nope")


async def test_an_empty_scratchpad_offers_only_the_tool_that_fills_it(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )

    offered = await build_scratchpad_toolset(promoted_kind="knowledge").get_tools(ctx)

    assert sorted(offered) == ["note"]


async def test_a_filled_scratchpad_offers_every_tool(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(ctx, title="T", summary="S", body="B")

    offered = await build_scratchpad_toolset(promoted_kind="knowledge").get_tools(ctx)

    assert len(offered) == 9


async def test_a_read_tool_called_twice_in_a_row_disappears(
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
) -> None:
    """Hiding the tool forces a different move before the next read."""
    seeding = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
    )
    await tools.note(seeding, title="T", summary="S", body="B")
    ctx = _ctx(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        messages=[
            ModelResponse(parts=[ToolCallPart(tool_name="list_notes")]),
            ModelResponse(parts=[ToolCallPart(tool_name="list_notes")]),
        ],
    )

    offered = await build_scratchpad_toolset(promoted_kind="knowledge").get_tools(ctx)

    assert "list_notes" not in offered
    assert "search_notes" in offered

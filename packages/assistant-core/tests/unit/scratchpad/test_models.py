"""The note models: their limits, their tag rule and their camelCase wire."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from assistant_core.scratchpad.models import (
    CompactionRun,
    Note,
    NoteCreate,
    NoteListResult,
    NoteRef,
    NoteSearchResult,
    NoteUpdate,
)


def _note_kwargs() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": "n-abc123",
        "conversation_id": uuid4(),
        "title": "Candidate search",
        "summary": "The run returned 1200 rows.",
        "body": "Details about the run and its inputs.",
        "tags": ["candidate", "run:Nightly"],
        "pinned": False,
        "body_tokens": 10,
        "created_at": now,
        "updated_at": now,
    }


def test_a_note_keeps_its_title_and_lowercases_its_tags() -> None:
    note = Note(**_note_kwargs())

    assert note.title == "Candidate search"
    assert note.tags == ["candidate", "run:nightly"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "x" * 121),
        ("title", ""),
        ("summary", "s" * 501),
        ("body", ""),
        ("body", "b" * 20001),
        ("body_tokens", -1),
    ],
)
def test_a_note_outside_its_limits_is_refused(field: str, value: object) -> None:
    kwargs = _note_kwargs()
    kwargs[field] = value

    with pytest.raises(ValidationError):
        Note(**kwargs)


def test_a_summary_at_the_cap_is_accepted() -> None:
    """The model is told to keep summaries near 280; 500 is the hard cap."""
    kwargs = _note_kwargs()
    kwargs["summary"] = "s" * 500

    assert len(Note(**kwargs).summary) == 500


def test_tags_are_stripped_deduplicated_and_kept_in_order() -> None:
    kwargs = _note_kwargs()
    kwargs["tags"] = ["  CaNDIdate ", "CANDIDATE", "run:Foo", "", "   "]

    assert Note(**kwargs).tags == ["candidate", "run:foo"]


def test_seventeen_tags_are_refused() -> None:
    kwargs = _note_kwargs()
    kwargs["tags"] = [f"tag-{i}" for i in range(17)]

    with pytest.raises(ValidationError):
        Note(**kwargs)


def test_a_new_note_defaults_to_no_tags_and_unpinned() -> None:
    created = NoteCreate(title="t", summary="s", body="b")

    assert created.tags == []
    assert created.pinned is False


def test_an_update_leaves_every_field_optional() -> None:
    patch = NoteUpdate(title="new title")

    assert patch.title == "new title"
    assert patch.summary is None
    assert patch.body is None


def _ref() -> NoteRef:
    return NoteRef(
        id="n-xyz",
        title="t",
        summary="s",
        tags=["x"],
        pinned=False,
        created_at=datetime.now(UTC),
    )


def test_a_reference_carries_no_body() -> None:
    assert "body" not in _ref().model_dump(mode="json")


def test_the_listing_envelope_reaches_the_model_in_camel_case() -> None:
    dumped = NoteListResult(
        total_notes=3,
        matches=[_ref()],
        summary="1 of 3 notes.",
    ).model_dump(by_alias=True, mode="json")

    assert dumped["totalNotes"] == 3
    assert "total_notes" not in dumped
    assert dumped["matches"][0]["id"] == "n-xyz"
    assert dumped["summary"] == "1 of 3 notes."


def test_the_search_envelope_adds_the_query() -> None:
    dumped = NoteSearchResult(
        total_notes=1,
        matches=[],
        summary="No notes match 'zqzqzq'.",
        query="zqzqzq",
    ).model_dump(by_alias=True, mode="json")

    assert dumped["query"] == "zqzqzq"
    assert dumped["totalNotes"] == 1
    assert dumped["matches"] == []


def test_a_compaction_run_records_why_it_ran() -> None:
    run = CompactionRun(
        id=1,
        conversation_id=uuid4(),
        triggered_at=datetime.now(UTC),
        before_count=55,
        after_count=18,
        before_tokens=12000,
        after_tokens=4200,
        model_id="openai:gpt-4.1-mini",
        cost_usd=Decimal("0.012345"),
        trigger_reason="both",
    )

    assert run.trigger_reason == "both"
    assert run.cost_usd == Decimal("0.012345")


def test_a_compaction_run_refuses_a_reason_the_gate_cannot_produce() -> None:
    with pytest.raises(ValidationError):
        CompactionRun(
            id=1,
            conversation_id=uuid4(),
            triggered_at=datetime.now(UTC),
            before_count=1,
            after_count=1,
            before_tokens=1,
            after_tokens=1,
            model_id="m",
            cost_usd=Decimal(0),
            trigger_reason="sometimes",
        )

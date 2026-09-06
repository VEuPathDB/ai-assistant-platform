from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    ReasoningDeltaChunk,
    ReasoningEndChunk,
    ReasoningStartChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolOutputAvailableChunk,
)

from assistant_core.conversation.vercel_adapter import PhaseStreamEmitter
from assistant_core.graph.turn_state import UserQuestionAnswer


def _assert_reasoning_well_formed(chunks: list[BaseChunk]) -> None:
    """Every reasoning-delta/end references an id that a reasoning-start opened
    and that wasn't already ended. Mirrors the frontend protocol validator in
    ``@ai-sdk/react``.
    """
    active: set[str] = set()
    for chunk in chunks:
        if isinstance(chunk, ReasoningStartChunk):
            assert chunk.id not in active, f"duplicate reasoning-start id {chunk.id}"
            active.add(chunk.id)
        elif isinstance(chunk, ReasoningDeltaChunk):
            assert chunk.id in active, (
                f"reasoning-delta for unopened id {chunk.id} "
                f"(active={active}, chunks={[type(c).__name__ for c in chunks]})"
            )
        elif isinstance(chunk, ReasoningEndChunk):
            assert chunk.id in active, f"reasoning-end for unopened id {chunk.id}"
            active.remove(chunk.id)


def _assert_text_well_formed(chunks: list[BaseChunk]) -> None:
    active: set[str] = set()
    for chunk in chunks:
        if isinstance(chunk, TextStartChunk):
            assert chunk.id not in active, f"duplicate text-start id {chunk.id}"
            active.add(chunk.id)
        elif isinstance(chunk, TextDeltaChunk):
            assert chunk.id in active, f"text-delta for unopened id {chunk.id}"
        elif isinstance(chunk, TextEndChunk):
            assert chunk.id in active, f"text-end for unopened id {chunk.id}"
            active.remove(chunk.id)


async def _interleaved_thinking_stream() -> AsyncIterator[object]:
    """Simulate pydantic-ai events from an Anthropic interleaved-thinking run:
    thinking block 0 → text block 1 → thinking block 2 → tool call 3.

    The iterator_with_part_end wrapper in pydantic-ai guarantees a
    ``PartEndEvent`` is emitted BEFORE each subsequent ``PartStartEvent`` and
    once more at stream end. We simulate that ordering here.
    """
    # --- thinking part 0 ---
    thinking_0 = ThinkingPart(content="first reasoning", provider_name="anthropic")
    yield PartStartEvent(index=0, part=thinking_0)
    yield PartDeltaEvent(
        index=0,
        delta=ThinkingPartDelta(content_delta=" continues", provider_name="anthropic"),
    )
    yield PartEndEvent(index=0, part=thinking_0, next_part_kind="text")

    # --- text part 1 ---
    text_1 = TextPart(content="visible reply", provider_name="anthropic")
    yield PartStartEvent(index=1, part=text_1, previous_part_kind="thinking")
    yield PartDeltaEvent(
        index=1,
        delta=TextPartDelta(content_delta=" more text", provider_name="anthropic"),
    )
    yield PartEndEvent(index=1, part=text_1, next_part_kind="thinking")

    # --- thinking part 2 (interleaved after text — this is the regression case) ---
    thinking_2 = ThinkingPart(content="second reasoning", provider_name="anthropic")
    yield PartStartEvent(index=2, part=thinking_2, previous_part_kind="text")
    yield PartDeltaEvent(
        index=2,
        delta=ThinkingPartDelta(
            content_delta=" more reasoning", provider_name="anthropic"
        ),
    )
    yield PartEndEvent(index=2, part=thinking_2, next_part_kind="tool-call")

    # --- tool call 3 (ensures the stream can close cleanly) ---
    tool_3 = ToolCallPart(
        tool_name="noop",
        args={"ok": True},
        tool_call_id="call-xyz",
    )
    yield PartStartEvent(index=3, part=tool_3, previous_part_kind="thinking")
    yield PartEndEvent(index=3, part=tool_3, next_part_kind=None)


@pytest.mark.anyio
async def test_interleaved_thinking_keeps_reasoning_ids_coherent() -> None:
    emitter = PhaseStreamEmitter(message_id="phase-test")
    chunks: list[BaseChunk] = [
        chunk async for chunk in emitter.chunks(_interleaved_thinking_stream())
    ]

    _assert_reasoning_well_formed(chunks)
    _assert_text_well_formed(chunks)

    # Sanity: we actually produced reasoning and text parts.
    assert any(isinstance(c, ReasoningStartChunk) for c in chunks), chunks
    assert any(isinstance(c, ReasoningDeltaChunk) for c in chunks), chunks
    assert any(isinstance(c, ReasoningEndChunk) for c in chunks), chunks
    assert any(isinstance(c, TextStartChunk) for c in chunks), chunks


async def _delta_before_start_stream() -> AsyncIterator[object]:
    """Regression for the concrete failure mode we saw with Haiku 4.5:

    - initial thinking start (ok)
    - later a second thinking delta arrives against the SAME vendor index
      after a text-part momentarily rotated ``self.message_id``.

    The buggy adapter uses ``self.message_id`` for every reasoning-delta,
    so after the text-start the second reasoning-delta references the
    text's id and the frontend rejects it.
    """
    thinking_0 = ThinkingPart(content="", provider_name="anthropic")
    yield PartStartEvent(index=0, part=thinking_0)
    yield PartDeltaEvent(
        index=0,
        delta=ThinkingPartDelta(content_delta="opening", provider_name="anthropic"),
    )
    yield PartEndEvent(index=0, part=thinking_0, next_part_kind="text")

    text_1 = TextPart(content="answer", provider_name="anthropic")
    yield PartStartEvent(index=1, part=text_1, previous_part_kind="thinking")
    yield PartEndEvent(index=1, part=text_1, next_part_kind="thinking")

    # The model resumes reasoning (fresh block, fresh index).
    thinking_2 = ThinkingPart(content="", provider_name="anthropic")
    yield PartStartEvent(index=2, part=thinking_2, previous_part_kind="text")
    yield PartDeltaEvent(
        index=2,
        delta=ThinkingPartDelta(
            content_delta="continuation", provider_name="anthropic"
        ),
    )
    yield PartEndEvent(index=2, part=thinking_2, next_part_kind=None)


@pytest.mark.anyio
async def test_thinking_after_text_uses_its_own_start_id() -> None:
    emitter = PhaseStreamEmitter(message_id="phase-test-2")
    chunks: list[BaseChunk] = [
        chunk async for chunk in emitter.chunks(_delta_before_start_stream())
    ]

    _assert_reasoning_well_formed(chunks)

    reasoning_starts = [c for c in chunks if isinstance(c, ReasoningStartChunk)]
    reasoning_deltas = [c for c in chunks if isinstance(c, ReasoningDeltaChunk)]
    assert len(reasoning_starts) == 2, [type(c).__name__ for c in chunks]
    start_ids = {s.id for s in reasoning_starts}
    for delta in reasoning_deltas:
        assert delta.id in start_ids, (
            f"delta id {delta.id} has no matching reasoning-start "
            f"(start ids: {start_ids})"
        )


async def _out_of_order_delta_stream() -> AsyncIterator[object]:
    """Direct regression for the failure mode: a ``PartDeltaEvent`` for an
    EARLIER thinking part (index 0) fires AFTER a later part's
    ``PartStartEvent`` has rotated ``self.message_id``.

    The underlying ``iterator_with_part_end`` normally guards against this,
    but the adapter must not rely on that guarantee — using a single mutable
    ``self.message_id`` makes every delta's id sensitive to ordering, which
    is exactly what breaks under Anthropic interleaved-thinking in
    practice. Asserting protocol-level correctness here catches the whole
    class of bug, not just one specific vendor ordering.
    """
    thinking_0 = ThinkingPart(content="", provider_name="anthropic")
    yield PartStartEvent(index=0, part=thinking_0)
    yield PartDeltaEvent(
        index=0,
        delta=ThinkingPartDelta(content_delta="a", provider_name="anthropic"),
    )

    # A text part starts while the thinking block is logically still open.
    # The adapter's ``self.message_id`` is rotated to the text id here.
    text_1 = TextPart(content="", provider_name="anthropic")
    yield PartStartEvent(index=1, part=text_1, previous_part_kind="thinking")
    yield PartDeltaEvent(
        index=1,
        delta=TextPartDelta(content_delta="t", provider_name="anthropic"),
    )

    # A late delta arrives for the original thinking part (index 0). A
    # well-implemented adapter routes it back to thinking_0's start id; the
    # buggy implementation uses whatever is in self.message_id (the text id)
    # and the frontend's ``@ai-sdk/react`` rejects it.
    yield PartDeltaEvent(
        index=0,
        delta=ThinkingPartDelta(content_delta="b", provider_name="anthropic"),
    )
    yield PartEndEvent(index=0, part=thinking_0, next_part_kind=None)
    yield PartEndEvent(index=1, part=text_1, next_part_kind=None)


@pytest.mark.anyio
async def test_out_of_order_thinking_delta_routes_to_own_start() -> None:
    emitter = PhaseStreamEmitter(message_id="phase-test-3")
    chunks: list[BaseChunk] = [
        chunk async for chunk in emitter.chunks(_out_of_order_delta_stream())
    ]

    _assert_reasoning_well_formed(chunks)
    _assert_text_well_formed(chunks)

    reasoning_starts = [c for c in chunks if isinstance(c, ReasoningStartChunk)]
    reasoning_deltas = [c for c in chunks if isinstance(c, ReasoningDeltaChunk)]
    text_starts = [c for c in chunks if isinstance(c, TextStartChunk)]

    assert len(reasoning_starts) == 1, chunks
    # The late delta carrying "b" must reference the single reasoning id.
    b_deltas = [d for d in reasoning_deltas if d.delta == "b"]
    assert len(b_deltas) == 1, reasoning_deltas
    assert b_deltas[0].id == reasoning_starts[0].id, (
        f"late reasoning delta used the wrong id: "
        f"{b_deltas[0].id} (start={reasoning_starts[0].id}, "
        f"text_start={text_starts[0].id if text_starts else None})"
    )


async def _consult_result_stream() -> AsyncIterator[object]:
    yield FunctionToolResultEvent(
        part=ToolReturnPart(
            tool_name="consult_user",
            content=[
                UserQuestionAnswer(
                    question_id="comparison_scope",
                    prompt="Retain both temperature-condition groups?",
                    chosen_labels=["Retain febrile and normal (recommended)"],
                )
            ],
            tool_call_id="call-consult",
        ),
    )


@pytest.mark.anyio
async def test_tool_output_carries_the_protocol_field_names() -> None:
    """A tool return reaches the wire under the aliases the protocol declares."""
    emitter = PhaseStreamEmitter(message_id="phase-consult")
    chunks: list[BaseChunk] = [
        chunk async for chunk in emitter.chunks(_consult_result_stream())
    ]
    outputs = [c for c in chunks if isinstance(c, ToolOutputAvailableChunk)]
    assert len(outputs) == 1
    assert outputs[0].output == [
        {
            "questionId": "comparison_scope",
            "prompt": "Retain both temperature-condition groups?",
            "chosenLabels": ["Retain febrile and normal (recommended)"],
            "note": "",
        }
    ]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

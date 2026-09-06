"""One turn, from the graph's first chunk to the message row it leaves behind."""

from __future__ import annotations

from tests.synthetic import (
    ADD_CALL_ID,
    ADD_PROMPT,
    ADD_TOOL,
    EPILOGUE_LABEL,
    PLAIN_PROMPT,
    PREPARING_LABEL,
    SYNTHETIC_ASSISTANT_ID,
    SyntheticRuntime,
)

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.conversation.ui_message_reducer import (
    reduce_chunks,
    split_into_turns,
)
from assistant_core.persistence.repositories._message_metadata import MessageMetadata
from assistant_core.persistence.repositories.message import MessagesRepository
from assistant_core.platform.db import async_session_factory
from assistant_core.registry import AssistantRegistry


async def test_a_turn_opens_with_start_and_closes_with_finish_then_done(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(PLAIN_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    types = [chunk["type"] for chunk in logged]
    assert types[0] == "start"
    assert types[-2:] == ["finish", "done"]
    assert logged[0]["messageId"] == str(outcome.turn_message_id)
    assert logged[-2]["finishReason"] == "stop"


async def test_every_chunk_the_graph_produced_is_in_the_durable_log(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(PLAIN_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)

    assert outcome.types() == [
        "data-turn-status",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "message-metadata",
        "finish-step",
        "data-turn-usage",
    ]
    # The driver's own framing brackets the graph's chunks in the log.
    assert [c["type"] for c in logged[:2]] == ["start", "data-turn-status"]
    assert [c["type"] for c in logged[2:-3]] == outcome.types()


async def test_the_assistant_s_epilogue_lands_after_its_graph_and_before_finish(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)

    assert [c["type"] for c in logged[-3:]] == ["data-turn-status", "finish", "done"]
    assert logged[-3]["data"]["label"] == EPILOGUE_LABEL
    assert logged[1]["data"]["label"] == PREPARING_LABEL


async def test_the_log_reduces_to_the_message_a_client_renders(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(PLAIN_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    message = reduce_chunks(logged, default_message_id=str(outcome.turn_message_id))

    assert message["id"] == str(outcome.turn_message_id)
    assert message["role"] == "assistant"
    text_parts = [p for p in message["parts"] if p["type"] == "text"]
    assert [p["text"] for p in text_parts] == [f"You said: {PLAIN_PROMPT}"]
    assert all(p["state"] == "done" for p in text_parts)


async def test_a_tool_call_reduces_to_a_part_carrying_its_input_and_output(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(ADD_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    message = reduce_chunks(logged, default_message_id=str(outcome.turn_message_id))

    tool_parts = [p for p in message["parts"] if p["type"] == f"tool-{ADD_TOOL}"]
    assert len(tool_parts) == 1
    assert tool_parts[0]["toolCallId"] == ADD_CALL_ID
    assert tool_parts[0]["state"] == "output-available"
    assert tool_parts[0]["input"] == {"a": 2, "b": 3}
    assert tool_parts[0]["output"] == 5
    assert [p["text"] for p in message["parts"] if p["type"] == "text"] == [
        "Result: 5."
    ]


async def test_the_turn_leaves_one_message_row_carrying_its_usage(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(PLAIN_PROMPT)

    async with async_session_factory() as session:
        rows = await MessagesRepository(session).list_messages_for_conversation(
            runtime.conversation_id,
        )

    assert [row.id for row in rows] == [outcome.turn_message_id]
    metadata = MessageMetadata.model_validate(rows[0].metadata_)
    assert metadata.usage is not None
    assert metadata.usage.total_tokens == runtime.ledger.total_tokens
    assert metadata.site_id == runtime.spec.assistant_id


async def test_one_done_chunk_terminates_the_turn_the_log_holds(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)
    await runtime.run(ADD_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    turns = split_into_turns(logged)

    assert len(turns) == 2
    assert all(turn[0]["type"] == "start" for turn in turns)
    assert all(turn[-1]["type"] == "done" for turn in turns)


def test_the_spec_carries_everything_a_deployment_needs_to_install_it(
    runtime: SyntheticRuntime,
) -> None:
    registry = AssistantRegistry(
        specs=[runtime.spec],
        default_id=SYNTHETIC_ASSISTANT_ID,
    )

    assert registry.resolve(SYNTHETIC_ASSISTANT_ID) is runtime.spec
    assert registry.checkpoint_types() == runtime.spec.checkpoint_types
    assert runtime.spec.memory_kinds == frozenset({"note"})
    assert runtime.spec.build_mock_model().model_name == "synthetic:scripted"

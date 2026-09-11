"""The prologue a turn opens with, and the hook a cancelled turn calls."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_state import TurnState
from assistant_core.platform.db import async_session_factory
from assistant_core.spec import AssistantSpec, TurnContextRequest


def _noop_graph(
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph: StateGraph[TurnState, TurnContext, TurnState, TurnState] = StateGraph(
        TurnState,
        context_schema=TurnContext,
    )

    async def _end(state: TurnState) -> TurnState:
        return state

    graph.add_node("end", _end)
    graph.add_edge(START, "end")
    return graph.compile(checkpointer=checkpointer)


def _silent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart(content="")])


async def _context(request: TurnContextRequest) -> TurnContext:
    return TurnContext(
        site_id=request.site_id,
        user_id=request.user_id,
        db_session_factory=async_session_factory,
        cancel_event=asyncio.Event(),
        memory_store=request.memory_store,
    )


def _spec(**overrides: Any) -> AssistantSpec:
    fields: dict[str, Any] = {
        "assistant_id": "alpha",
        "build_graph": _noop_graph,
        "build_initial_state": lambda start: TurnState(**start.state_kwargs()),
        "build_turn_context": _context,
        "build_mock_model": lambda: FunctionModel(_silent),
    }
    fields.update(overrides)
    return AssistantSpec.model_validate(fields)


async def test_a_spec_with_no_hooks_opens_and_cancels_with_nothing() -> None:
    spec = _spec()
    conversation_id = uuid4()

    token = await spec.turn_prologue(conversation_id)
    await spec.turn_cancel(conversation_id, token)

    assert token is None


async def test_the_token_the_prologue_returns_reaches_the_cancel_hook() -> None:
    conversation_id = uuid4()
    restored: list[tuple[UUID, str]] = []

    async def _prologue(started: UUID) -> str:
        return f"revision-of-{started}"

    async def _cancel(cancelled: UUID, token: str) -> None:
        restored.append((cancelled, token))

    spec = _spec(turn_prologue=_prologue, turn_cancel=_cancel)

    token = await spec.turn_prologue(conversation_id)
    await spec.turn_cancel(conversation_id, token)

    assert restored == [(conversation_id, f"revision-of-{conversation_id}")]

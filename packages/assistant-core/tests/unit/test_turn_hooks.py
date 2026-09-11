"""The prologue a turn opens with, and the hook a cancelled turn calls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from tests.synthetic import TurnRequest, drive_turn

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
        cancel_event=request.cancel_event,
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


@dataclass
class _ListWriter:
    """A chunk sink that appends each chunk's kind to the shared order."""

    conversation_id: UUID
    turn_id: UUID
    order: list[str]

    async def write(self, chunk: dict[str, Any]) -> int:
        self.order.append(str(chunk["type"]))
        return len(self.order)


def _recording_graph(
    order: list[str],
) -> Callable[[BaseCheckpointSaver[Any]], CompiledStateGraph[Any, Any, Any, Any]]:
    """A graph whose one node says when it ran."""

    def build(
        checkpointer: BaseCheckpointSaver[Any],
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        graph: StateGraph[TurnState, TurnContext, TurnState, TurnState] = StateGraph(
            TurnState,
            context_schema=TurnContext,
        )

        async def _run(state: TurnState) -> TurnState:
            order.append("graph")
            return state

        graph.add_node("run", _run)
        graph.add_edge(START, "run")
        return graph.compile(checkpointer=checkpointer)

    return build


async def _drive(spec: AssistantSpec, order: list[str], *, stopped: bool) -> None:
    """Run one turn through the reference driver, on an in-memory log."""
    conversation_id, user_id = uuid4(), uuid4()
    cancel = asyncio.Event()
    if stopped:
        cancel.set()
    context = await spec.build_turn_context(
        TurnContextRequest(
            conversation=None,
            site_id="synthetic",
            user_id=user_id,
            memory_store=None,
            cancel_event=cancel,
            phase_models={},
            phase_reasoning={},
        ),
    )
    await drive_turn(
        TurnRequest(
            spec=spec,
            graph=spec.build_graph(InMemorySaver()),
            writer=_ListWriter(
                conversation_id=conversation_id,
                turn_id=uuid4(),
                order=order,
            ),
            context=context,
            conversation_id=conversation_id,
            user_id=user_id,
            prompt="hello",
        ),
    )


def _hook_spec(order: list[str]) -> AssistantSpec:
    async def _prologue(started: UUID) -> str:
        del started
        order.append("prologue")
        return "token"

    async def _cancel(stopped: UUID, token: str) -> None:
        del stopped, token
        order.append("cancel")

    async def _epilogue(finished: UUID) -> Sequence[dict[str, Any]]:
        del finished
        order.append("epilogue")
        return ()

    return _spec(
        build_graph=_recording_graph(order),
        turn_prologue=_prologue,
        turn_cancel=_cancel,
        turn_epilogue=_epilogue,
    )


async def test_a_turn_runs_the_prologue_then_the_graph_then_the_epilogue() -> None:
    order: list[str] = []

    await _drive(_hook_spec(order), order, stopped=False)

    assert order == [
        "prologue",
        "start",
        "data-turn-status",
        "graph",
        "epilogue",
        "finish",
        "done",
    ]


async def test_a_stopped_turn_calls_the_cancel_hook_before_it_says_it_stopped() -> None:
    order: list[str] = []

    await _drive(_hook_spec(order), order, stopped=True)

    assert order == [
        "prologue",
        "start",
        "data-turn-status",
        "graph",
        "cancel",
        "data-turn-stopped",
        "epilogue",
        "finish",
        "done",
    ]

"""The registry the runtime resolves a turn's assistant through."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_state import TurnState
from assistant_core.platform.db import async_session_factory
from assistant_core.registry import (
    AssistantRegistry,
    DuplicateAssistantError,
    UnknownAssistantError,
    UnknownDefaultAssistantError,
)
from assistant_core.spec import (
    AssistantSpec,
    TurnContextRequest,
    TurnStart,
    turn_input,
)


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


def _spec(assistant_id: str, **overrides: Any) -> AssistantSpec:
    fields: dict[str, Any] = {
        "assistant_id": assistant_id,
        "build_graph": _noop_graph,
        "build_initial_state": lambda start: TurnState(**start.state_kwargs()),
        "build_turn_context": _context,
        "build_mock_model": lambda: FunctionModel(_silent),
    }
    fields.update(overrides)
    return AssistantSpec.model_validate(fields)


def test_resolve_returns_the_registered_spec() -> None:
    registry = AssistantRegistry(specs=[_spec("alpha")], default_id="alpha")

    assert registry.resolve("alpha").assistant_id == "alpha"


def test_resolve_refuses_an_unknown_id() -> None:
    registry = AssistantRegistry(specs=[_spec("alpha")], default_id="alpha")

    with pytest.raises(UnknownAssistantError) as raised:
        registry.resolve("beta")

    assert raised.value.assistant_id == "beta"
    assert raised.value.known == ("alpha",)


def test_a_default_outside_the_registry_is_refused() -> None:
    with pytest.raises(UnknownDefaultAssistantError):
        AssistantRegistry(specs=[_spec("alpha")], default_id="beta")


def test_two_specs_cannot_claim_one_id() -> None:
    with pytest.raises(DuplicateAssistantError, match="alpha"):
        AssistantRegistry(specs=[_spec("alpha"), _spec("alpha")], default_id="alpha")


def test_checkpoint_types_are_the_union_over_installed_assistants() -> None:
    class _Left:
        pass

    class _Right:
        pass

    registry = AssistantRegistry(
        specs=[
            _spec("alpha", checkpoint_types=(_Left,)),
            _spec("beta", checkpoint_types=(_Right, _Left)),
        ],
        default_id="alpha",
    )

    assert set(registry.checkpoint_types()) == {_Left, _Right}
    assert len(registry.checkpoint_types()) == 2


def test_ids_are_reported_in_registration_order() -> None:
    registry = AssistantRegistry(
        specs=[_spec("alpha"), _spec("beta")],
        default_id="beta",
    )

    assert registry.ids() == ("alpha", "beta")
    assert registry.default_id == "beta"


def test_a_spec_is_frozen() -> None:
    spec = _spec("alpha")

    with pytest.raises(ValueError, match="frozen"):
        spec.assistant_id = "beta"


def test_turn_start_omits_the_message_fields_on_a_resume() -> None:
    """A resume must not blank the prompt the checkpoint already holds."""
    start = TurnStart(
        conversation_id=uuid4(),
        user_id=uuid4(),
        site_id="plasmodb",
        mode="strategy",
        turn_message_id=uuid4(),
        turn_start_event_id=3,
        is_resume=True,
        user_message_id=uuid4(),
        user_prompt="ignored",
    )

    kwargs = start.state_kwargs()

    assert "user_prompt" not in kwargs
    assert "user_message_id" not in kwargs
    assert "user_parts" not in kwargs
    assert kwargs["site_id"] == "plasmodb"


def test_turn_start_carries_the_message_fields_on_a_normal_turn() -> None:
    message_id = uuid4()
    start = TurnStart(
        conversation_id=uuid4(),
        user_id=uuid4(),
        site_id="plasmodb",
        mode="strategy",
        turn_message_id=uuid4(),
        turn_start_event_id=0,
        is_resume=False,
        user_message_id=message_id,
        user_prompt="find kinases",
    )

    kwargs = start.state_kwargs()

    assert kwargs["user_message_id"] == message_id
    assert kwargs["user_prompt"] == "find kinases"
    assert [part.text for part in kwargs["user_parts"]] == ["find kinases"]


def test_the_turn_input_is_only_what_the_state_factory_set() -> None:
    """A field the factory left alone keeps its checkpointed value."""
    state = TurnState(
        conversation_id=uuid4(),
        user_id=uuid4(),
        site_id="plasmodb",
        mode="strategy",
    )

    assert set(turn_input(state)) == {
        "conversation_id",
        "user_id",
        "site_id",
        "mode",
    }

"""Every function tool stays on every request, and the model may call only the
ones no rule withholds."""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ToolOrOutput

from assistant_core.capabilities.allowed_tools import AllowedTools, WithholdRule


class _SentTool(BaseModel):
    name: str


class _SentBody(BaseModel):
    """The two fields of a Responses request this suite reads."""

    model_config = ConfigDict(extra="ignore")

    tools: list[_SentTool]
    tool_choice: dict[str, object]


def _withhold_build(ctx: RunContext[None], names: Sequence[str]) -> set[str]:
    del ctx
    return {name for name in names if name == "build"}


async def _withhold_nothing(ctx: RunContext[None], names: Sequence[str]) -> set[str]:
    del ctx, names
    return set()


def _agent(
    model: FunctionModel | OpenAIResponsesModel, *rules: WithholdRule[None]
) -> Agent[None, str]:
    agent: Agent[None, str] = Agent(
        model, capabilities=[AllowedTools[None](rules=list(rules))]
    )

    @agent.tool_plain
    def read() -> str:
        """Read the strategy."""
        return "read"

    @agent.tool_plain
    def build() -> str:
        """Build the strategy."""
        return "built"

    return agent


def _recording(seen: list[AgentInfo]) -> FunctionModel:
    def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        seen.append(info)
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(_model)


async def test_a_withheld_tool_stays_listed_and_cannot_be_chosen() -> None:
    seen: list[AgentInfo] = []

    await _agent(_recording(seen), _withhold_build).run("go")

    [info] = seen
    assert [tool.name for tool in info.function_tools] == ["read", "build"]
    assert (info.model_settings or {}).get("tool_choice") == ToolOrOutput(
        function_tools=["read"]
    )


async def test_nothing_withheld_sets_no_tool_choice() -> None:
    seen: list[AgentInfo] = []

    await _agent(_recording(seen), _withhold_nothing).run("go")

    [info] = seen
    assert "tool_choice" not in (info.model_settings or {})


async def test_the_openai_request_lists_every_tool_and_allows_the_rest() -> None:
    sent: list[_SentBody] = []

    def _refuse(request: httpx2.Request) -> httpx2.Response:
        sent.append(_SentBody.model_validate(json.loads(request.content)))
        return httpx2.Response(
            400, json={"error": {"message": "stop", "type": "invalid_request_error"}}
        )

    client = AsyncOpenAI(
        api_key="test-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_refuse)),
        max_retries=0,
    )
    model = OpenAIResponsesModel(
        "gpt-5.6-luna", provider=OpenAIProvider(openai_client=client)
    )

    with pytest.raises(ModelHTTPError, match="stop"):
        await _agent(model, _withhold_build).run("go")

    [body] = sent
    assert [tool.name for tool in body.tools] == ["read", "build"]
    assert body.tool_choice == {
        "type": "allowed_tools",
        "mode": "auto",
        "tools": [{"type": "function", "name": "read"}],
    }


async def test_a_withheld_tool_is_refused_if_a_model_calls_it_anyway() -> None:
    """A provider that ignores the choice still cannot run a withheld tool."""
    told: list[str] = []

    def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        refusals = [
            part.model_response()
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        if refusals:
            told.extend(refusals)
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("build", {})])

    built: list[str] = []
    agent: Agent[None, str] = Agent(
        FunctionModel(_model),
        capabilities=[AllowedTools[None](rules=[_withhold_build])],
    )

    @agent.tool_plain
    def build() -> str:
        """Build the strategy."""
        built.append("built")
        return "built"

    await agent.run("go")

    assert built == []
    assert len(told) == 1
    assert "build cannot be called now" in told[0]

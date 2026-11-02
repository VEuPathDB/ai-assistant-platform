"""Each request of a run carries the model's own earlier reasoning in the
provider's native form, after every history processor has run."""

from __future__ import annotations

import json

import httpx2
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from assistant_core.conversation.history import HISTORY_PROCESSORS
from assistant_core.models.settings import build_model_settings

_OPENAI_ID = "openai:gpt-5.6-luna"
_ANTHROPIC_ID = "anthropic:claude-sonnet-5"
_EXCHANGES = 20
_BULKY_RESULT = "x" * 120_000


class _SentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "message"
    id: str | None = None
    encrypted_content: str | None = None


class _SentResponsesBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input: list[_SentItem]


class _SentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    id: str | None = None
    signature: str | None = None


class _SentMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: list[_SentBlock]


class _SentMessagesBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[_SentMessage]


def _transport(
    sent: list[bytes], replies: list[dict[str, object]]
) -> httpx2.AsyncClient:
    def _answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request.content)
        return httpx2.Response(200, json=replies[len(sent) - 1])

    return httpx2.AsyncClient(transport=httpx2.MockTransport(_answer))


def _openai_model(
    sent: list[bytes], replies: list[dict[str, object]]
) -> OpenAIResponsesModel:
    client = AsyncOpenAI(
        api_key="test-key", http_client=_transport(sent, replies), max_retries=0
    )
    return OpenAIResponsesModel(
        "gpt-5.6-luna", provider=OpenAIProvider(openai_client=client)
    )


def _anthropic_model(
    sent: list[bytes], replies: list[dict[str, object]]
) -> AnthropicModel:
    client = AsyncAnthropic(
        api_key="test-key", http_client=_transport(sent, replies), max_retries=0
    )
    return AnthropicModel(
        "claude-sonnet-5", provider=AnthropicProvider(anthropic_client=client)
    )


def _responses_reply(n: int, output: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": f"resp_{n}",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-luna",
        "status": "completed",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": output,
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 2,
        },
    }


def _reasoning(n: int) -> dict[str, object]:
    return {
        "type": "reasoning",
        "id": f"rs_{n}",
        "summary": [],
        "encrypted_content": f"enc-{n}",
    }


_FINAL_ANSWER = _responses_reply(
    9,
    [
        {
            "type": "message",
            "id": "msg_9",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "done", "annotations": []}],
        }
    ],
)

_ANTHROPIC_ANSWER: dict[str, object] = {
    "id": "msg_9",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5",
    "content": [{"type": "text", "text": "done"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def _processed(messages: list[ModelMessage]) -> list[ModelMessage]:
    out = list(messages)
    for processor in HISTORY_PROCESSORS:
        out = processor(out)
    return out


def _long_run(provider: str) -> list[ModelMessage]:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="find the genes")])
    ]
    for n in range(_EXCHANGES):
        messages.append(
            ModelResponse(
                parts=[
                    ThinkingPart(
                        content=f"thought {n}",
                        id=f"rs_{n}",
                        signature=f"enc-{n}",
                        provider_name=provider,
                    ),
                    ToolCallPart(
                        tool_name="lookup",
                        args={"n": n},
                        tool_call_id=f"call_{n}",
                        id=f"fc_{n}",
                        provider_name=provider,
                    ),
                ],
                provider_name=provider,
            )
        )
        messages.append(
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="lookup",
                        content=_BULKY_RESULT,
                        tool_call_id=f"call_{n}",
                    )
                ]
            )
        )
    return messages


def _kept_exchanges(messages: list[ModelMessage]) -> list[int]:
    return [
        int(part.tool_call_id.removeprefix("call_"))
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.tool_calls
    ]


def _openai_pairs(body: bytes) -> list[tuple[str, str | None, str | None]]:
    items = _SentResponsesBody.model_validate(json.loads(body)).input
    return [
        (item.id or "", item.encrypted_content, items[i + 1].id)
        for i, item in enumerate(items)
        if item.type == "reasoning"
    ]


def _expected_openai_pairs(kept: list[int]) -> list[tuple[str, str | None, str | None]]:
    return [(f"rs_{n}", f"enc-{n}", f"fc_{n}") for n in kept]


async def test_a_later_call_carries_the_earlier_encrypted_reasoning() -> None:
    sent: list[bytes] = []
    first = _responses_reply(
        1,
        [
            _reasoning(1),
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": '{"n": 1}',
                "status": "completed",
            },
        ],
    )
    agent: Agent[None, str] = Agent(
        _openai_model(sent, [first, _FINAL_ANSWER]),
        model_settings=build_model_settings(_OPENAI_ID),
        deps_type=type(None),
        capabilities=[ProcessHistory[None](p) for p in HISTORY_PROCESSORS],
    )

    @agent.tool_plain
    def lookup(n: int) -> str:
        """Look one up."""
        return f"found {n}"

    result = await agent.run("find the genes")

    assert result.output == "done"
    assert _openai_pairs(sent[1]) == [("rs_1", "enc-1", "fc_1")]


async def test_a_rewritten_history_keeps_reasoning_before_its_call() -> None:
    history = _long_run("openai")
    processed = _processed(history)
    kept = _kept_exchanges(processed)
    sent: list[bytes] = []

    await _openai_model(sent, [_FINAL_ANSWER]).request(
        processed, build_model_settings(_OPENAI_ID), ModelRequestParameters()
    )

    assert len(processed) < len(history)
    assert kept == [_EXCHANGES - 2, _EXCHANGES - 1]
    assert _openai_pairs(sent[0]) == _expected_openai_pairs(kept)


async def test_an_answered_orphan_keeps_its_reasoning_before_its_call() -> None:
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="find the genes")]),
        *_long_run("openai")[1:2],
        ModelRequest(parts=[UserPromptPart(content="go on")]),
    ]
    processed = _processed(history)
    sent: list[bytes] = []

    await _openai_model(sent, [_FINAL_ANSWER]).request(
        processed, build_model_settings(_OPENAI_ID), ModelRequestParameters()
    )

    returns = [
        part
        for message in processed
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert [part.tool_call_id for part in returns] == ["call_0"]
    assert _openai_pairs(sent[0]) == _expected_openai_pairs([0])


async def test_anthropic_keeps_each_signed_thinking_block_before_its_tool_use() -> None:
    processed = _processed(_long_run("anthropic"))
    kept = _kept_exchanges(processed)
    sent: list[bytes] = []

    await _anthropic_model(sent, [_ANTHROPIC_ANSWER]).request(
        processed, build_model_settings(_ANTHROPIC_ID), ModelRequestParameters()
    )

    body = _SentMessagesBody.model_validate(json.loads(sent[0]))
    sent_turns = [
        [(block.type, block.signature or block.id) for block in message.content]
        for message in body.messages
        if message.role == "assistant"
    ]
    assert sent_turns == [
        [("thinking", f"enc-{n}"), ("tool_use", f"call_{n}")] for n in kept
    ]

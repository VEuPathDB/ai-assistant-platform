"""Each model request carries its reasoning effort on its own ``chat`` span.

The provider is installed through the package's own install function, so the
agent library places its instrumentation the way a host process does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings

from assistant_core.models.settings import build_model_settings
from assistant_core.platform.observability import (
    ReasoningEffortOnSpan,
    install_tracer_provider,
    reset_tracer_provider,
)

_EFFORT = "gen_ai.request.reasoning_effort"
_ANSWER = "three genes"


@pytest.fixture
def spans() -> Generator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    install_tracer_provider(provider, include_content=False)
    try:
        yield exporter
    finally:
        reset_tracer_provider()
        provider.shutdown()


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart(content=_ANSWER)])


async def _stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    del messages, info
    yield _ANSWER


def _agent() -> Agent[None, str]:
    model = FunctionModel(
        _answer,
        stream_function=_stream,
        profile=ModelProfile(supports_thinking=True),
    )
    return Agent(model, capabilities=[ReasoningEffortOnSpan()])


def _only(spans: InMemorySpanExporter, prefix: str) -> ReadableSpan:
    matching = [s for s in spans.get_finished_spans() if s.name.startswith(prefix)]
    assert len(matching) == 1
    return matching[0]


def _chat_attributes(spans: InMemorySpanExporter) -> dict[str, object]:
    return dict(_only(spans, "chat ").attributes or {})


async def test_the_unified_level_is_on_the_chat_span(
    spans: InMemorySpanExporter,
) -> None:
    result = await _agent().run(
        "Which genes?", model_settings=ModelSettings(thinking="high")
    )

    assert result.output == _ANSWER
    assert _chat_attributes(spans)[_EFFORT] == "high"


async def test_the_effort_is_on_the_chat_span_and_not_on_the_run_span(
    spans: InMemorySpanExporter,
) -> None:
    await _agent().run("Which genes?", model_settings=ModelSettings(thinking="low"))

    chat = _only(spans, "chat ")
    run = _only(spans, "invoke_agent")

    assert chat.parent is not None
    assert chat.parent.span_id == run.context.span_id
    assert (chat.attributes or {})[_EFFORT] == "low"
    assert _EFFORT not in (run.attributes or {})


async def test_an_openai_max_effort_is_on_the_chat_span(
    spans: InMemorySpanExporter,
) -> None:
    await _agent().run(
        "Which genes?",
        model_settings=build_model_settings("openai:gpt-6-luna", thinking="max"),
    )

    assert _chat_attributes(spans)[_EFFORT] == "max"


async def test_the_provider_effort_wins_over_the_unified_level(
    spans: InMemorySpanExporter,
) -> None:
    await _agent().run(
        "Which genes?",
        model_settings=OpenAIResponsesModelSettings(
            thinking="low", openai_reasoning_effort="max"
        ),
    )

    assert _chat_attributes(spans)[_EFFORT] == "max"


async def test_a_streamed_request_carries_the_effort(
    spans: InMemorySpanExporter,
) -> None:
    async with _agent().run_stream_events(
        "Which genes?", model_settings=ModelSettings(thinking="medium")
    ) as events:
        async for _event in events:
            pass

    assert _chat_attributes(spans)[_EFFORT] == "medium"


async def test_no_thinking_setting_records_no_effort(
    spans: InMemorySpanExporter,
) -> None:
    await _agent().run("Which genes?")

    assert _EFFORT not in _chat_attributes(spans)


@pytest.mark.parametrize("thinking", [True, False])
async def test_a_bool_thinking_setting_records_no_effort(
    spans: InMemorySpanExporter, thinking: bool
) -> None:
    await _agent().run("Which genes?", model_settings=ModelSettings(thinking=thinking))

    assert _EFFORT not in _chat_attributes(spans)

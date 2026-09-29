"""A turn is one trace, and the process exports only where the environment points.

Each test installs a tracer provider of its own with an in-memory exporter, so
the spans it reads are the spans it produced.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from assistant_core.platform.observability import (
    PricedSpanExporter,
    TraceScope,
    current_trace_id,
    install_observability,
    install_tracer_provider,
    otlp_exporter_headers,
    reset_tracer_provider,
    traced,
    traced_roots_sampler,
)

_CONVERSATION = UUID("11111111-1111-1111-1111-111111111111")
_USER = UUID("22222222-2222-2222-2222-222222222222")
_PROMPT = "Which genes carry a signal peptide?"


def _scope() -> TraceScope:
    return TraceScope(
        name="pathfinder",
        session_id=_CONVERSATION,
        user_id=_USER,
        tags=("plasmodb",),
        metadata={"assistant_id": "pathfinder", "site_id": "plasmodb"},
        input_text=_PROMPT,
    )


def _exporter(*, include_content: bool) -> Generator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    install_tracer_provider(provider, include_content=include_content)
    try:
        yield exporter
    finally:
        reset_tracer_provider()
        provider.shutdown()


@pytest.fixture
def spans() -> Generator[InMemorySpanExporter]:
    yield from _exporter(include_content=True)


@pytest.fixture
def spans_without_content() -> Generator[InMemorySpanExporter]:
    yield from _exporter(include_content=False)


async def _one_traced_run() -> str | None:
    with traced(_scope()):
        trace_id = current_trace_id()
        await Agent(TestModel(custom_output_text="three genes")).run(_PROMPT)
    return trace_id


def _root(finished: tuple[ReadableSpan, ...]) -> ReadableSpan:
    roots = [span for span in finished if span.parent is None]
    assert [span.name for span in roots] == ["pathfinder"]
    return roots[0]


async def test_a_turn_is_one_root_span_with_the_trace_attributes(
    spans: InMemorySpanExporter,
) -> None:
    await _one_traced_run()

    attributes = dict(_root(spans.get_finished_spans()).attributes or {})

    assert attributes["session.id"] == str(_CONVERSATION)
    assert attributes["user.id"] == str(_USER)
    assert attributes["langfuse.session.id"] == str(_CONVERSATION)
    assert attributes["langfuse.user.id"] == str(_USER)
    assert attributes["langfuse.trace.name"] == "pathfinder"
    assert attributes["langfuse.trace.tags"] == ("plasmodb",)
    assert attributes["langfuse.trace.metadata.site_id"] == "plasmodb"
    assert attributes["langfuse.trace.metadata.assistant_id"] == "pathfinder"
    assert attributes["langfuse.trace.input"] == _PROMPT


async def test_a_model_run_inside_the_turn_is_its_child(
    spans: InMemorySpanExporter,
) -> None:
    trace_id = await _one_traced_run()

    finished = spans.get_finished_spans()
    root = _root(finished)
    model_calls = [
        s for s in finished if "gen_ai.request.model" in (s.attributes or {})
    ]

    assert trace_id == format(root.context.trace_id, "032x")
    assert {span.context.trace_id for span in finished} == {root.context.trace_id}
    assert [span.name for span in model_calls] == ["chat test"]
    agent_run = next(s for s in finished if s.name.startswith("invoke_agent"))
    assert agent_run.parent is not None
    assert agent_run.parent.span_id == root.context.span_id


async def test_every_span_of_the_turn_carries_the_session_and_the_user(
    spans: InMemorySpanExporter,
) -> None:
    await _one_traced_run()

    children = [s for s in spans.get_finished_spans() if s.parent is not None]

    assert len(children) >= 2
    assert {(s.attributes or {}).get("session.id") for s in children} == {
        str(_CONVERSATION)
    }
    assert {(s.attributes or {}).get("user.id") for s in children} == {str(_USER)}


async def test_content_off_exports_no_prompt_text(
    spans_without_content: InMemorySpanExporter,
) -> None:
    await _one_traced_run()

    exported = " ".join(
        str(value)
        for span in spans_without_content.get_finished_spans()
        for value in (span.attributes or {}).values()
    )

    assert _PROMPT not in exported
    assert "three genes" not in exported


def test_no_span_outside_a_turn_has_a_trace_id() -> None:
    assert current_trace_id() is None


def test_no_endpoint_installs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    before = trace.get_tracer_provider()

    installed = install_observability(
        service_name="assistant",
        service_version="0.0.0",
        environment="test",
        include_content=False,
    )

    assert installed is False
    assert trace.get_tracer_provider() is before


def test_a_grpc_protocol_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")

    with pytest.raises(ValueError, match="http/protobuf"):
        install_observability(
            service_name="assistant",
            service_version="0.0.0",
            environment="test",
            include_content=False,
        )


def test_host_headers_join_the_environment_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "x-tenant=lab,x-scope=turns")

    headers = otlp_exporter_headers({"Authorization": "Basic cGs6c2s="})

    assert headers == {
        "x-tenant": "lab",
        "x-scope": "turns",
        "authorization": "Basic cGs6c2s=",
    }


def test_a_priced_model_call_is_exported_with_its_cost() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(PricedSpanExporter(exporter)))
    tracer = provider.get_tracer("pricing")

    with tracer.start_as_current_span(
        "chat priced", attributes={"operation.cost": 0.0125}
    ):
        pass
    with tracer.start_as_current_span("chat unpriced"):
        pass
    provider.shutdown()

    costs = {
        span.name: (span.attributes or {}).get("gen_ai.usage.cost")
        for span in exporter.get_finished_spans()
    }
    assert costs == {"chat priced": 0.0125, "chat unpriced": None}


def _sampled_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=traced_roots_sampler())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_a_span_opened_outside_a_turn_or_a_request_is_not_exported() -> None:
    provider, exporter = _sampled_exporter()
    install_tracer_provider(provider, include_content=True)
    try:
        with (
            provider.get_tracer("db").start_as_current_span("SELECT 1"),
            provider.get_tracer("http").start_as_current_span("GET /models"),
        ):
            pass
    finally:
        reset_tracer_provider()
        provider.shutdown()

    assert exporter.get_finished_spans() == ()


async def test_every_span_under_a_turn_is_exported() -> None:
    provider, exporter = _sampled_exporter()
    install_tracer_provider(provider, include_content=True)
    try:
        with traced(_scope()):
            with provider.get_tracer("db").start_as_current_span("SELECT 1"):
                pass
            await Agent(TestModel(custom_output_text="three genes")).run(_PROMPT)
    finally:
        reset_tracer_provider()
        provider.shutdown()

    names = {span.name for span in exporter.get_finished_spans()}
    assert "pathfinder" in names
    assert "SELECT 1" in names
    assert any(name.startswith("chat ") for name in names)


def test_a_server_request_is_exported_with_its_children() -> None:
    provider, exporter = _sampled_exporter()
    try:
        tracer = provider.get_tracer("http")
        with (
            tracer.start_as_current_span("GET /api/v1/sites", kind=SpanKind.SERVER),
            provider.get_tracer("db").start_as_current_span("SELECT sites"),
        ):
            pass
    finally:
        provider.shutdown()

    assert sorted(span.name for span in exporter.get_finished_spans()) == [
        "GET /api/v1/sites",
        "SELECT sites",
    ]

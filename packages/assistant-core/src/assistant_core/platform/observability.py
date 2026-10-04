"""The process's tracer and exporter, the root span that makes a turn one trace,
and the attributes a model request's span carries.

The exporter reads the standard OpenTelemetry variables. A process with no OTLP
endpoint installs nothing, and every span it opens is a no-op.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, override
from uuid import UUID, uuid4

from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
)
from opentelemetry.trace import Link, SpanKind, TraceState
from opentelemetry.util.re import parse_env_headers
from opentelemetry.util.types import Attributes
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai import Agent, InstrumentationSettings
from pydantic_ai.capabilities.abstract import (
    AbstractCapability,
    WrapModelRequestHandler,
)
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.settings import ThinkingEffort
from pydantic_ai.tools import RunContext
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from assistant_core.platform.logging import get_logger
from assistant_core.platform.metrics import install_meter_provider, reset_meter_provider

logger = get_logger(__name__)

_TRACER_NAME = "assistant_core"


class _OtlpEnvironment(BaseSettings):
    """The standard OpenTelemetry exporter variables this module reads."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_traces_endpoint: str = ""
    otel_exporter_otlp_metrics_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_exporter_otlp_protocol: Literal["http/protobuf"] = "http/protobuf"

    @property
    def exports_traces(self) -> bool:
        return bool(
            self.otel_exporter_otlp_endpoint or self.otel_exporter_otlp_traces_endpoint
        )


class TraceScope(BaseModel):
    """One root span: its name, the session and user it belongs to, and its labels."""

    model_config = ConfigDict(frozen=True)

    name: str
    session_id: UUID
    user_id: UUID
    tags: tuple[str, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)
    input_text: str = ""


# The session and user of the root span in force, stamped on every span under it.
_trace_identity: ContextVar[Mapping[str, str] | None] = ContextVar(
    "trace_identity", default=None
)


class _TraceIdentity(SpanProcessor):
    """Stamps the root span's session and user on each span started beneath it."""

    def on_start(
        self, span: Span, parent_context: context.Context | None = None
    ) -> None:
        del parent_context
        identity = _trace_identity.get()
        if identity:
            span.set_attributes(identity)

    def on_end(self, span: ReadableSpan) -> None:
        del span


_ROOT_MARK = "langfuse.trace.name"


class _TracedRoots(Sampler):
    """Records a root span only when ``traced`` opened it or a server request did.

    A statement or a request made outside a turn would otherwise become a
    trace of its own with no session.
    """

    @override
    def should_sample(
        self,
        parent_context: context.Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        del parent_context, trace_id, name, links
        wanted = kind is SpanKind.SERVER or bool(
            attributes and _ROOT_MARK in attributes
        )
        decision = Decision.RECORD_AND_SAMPLE if wanted else Decision.DROP
        return SamplingResult(decision, attributes if wanted else None, trace_state)

    @override
    def get_description(self) -> str:
        return "TracedRoots"


def traced_roots_sampler() -> Sampler:
    """The sampler a provider takes so only turns and requests are exported."""
    return ParentBased(root=_TracedRoots())


class PricedSpanExporter(SpanExporter):
    """Exports each priced model call with its price as ``gen_ai.usage.cost``.

    The agent library records a call's price as ``operation.cost``; a backend
    that reads the GenAI cost attribute then shows the price the runtime charged.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([_priced(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _priced(span: ReadableSpan) -> ReadableSpan:
    attributes = dict(span.attributes or {})
    if "operation.cost" not in attributes or "gen_ai.usage.cost" in attributes:
        return span
    attributes["gen_ai.usage.cost"] = attributes["operation.cost"]
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


_REASONING_EFFORT_ATTRIBUTE = "gen_ai.request.reasoning_effort"


class _RequestEffort(BaseModel):
    """The two keys of a request's model settings that name its reasoning effort."""

    model_config = ConfigDict(extra="ignore")

    openai_reasoning_effort: str | None = None
    thinking: ThinkingEffort | None = None

    @field_validator("thinking", mode="before")
    @classmethod
    def _a_bool_names_no_level(cls, value: object) -> object:
        return None if value is True or value is False else value

    @property
    def level(self) -> str | None:
        """The provider's own effort when set, because the provider reads it first."""
        return self.openai_reasoning_effort or self.thinking


@dataclass
class ReasoningEffortOnSpan(AbstractCapability[object]):
    """Writes each model request's reasoning effort on its ``chat`` span.

    The agent library opens that span outside every other capability, so the
    span in force here is the request's own. A request with no effort level
    gets no attribute.
    """

    async def wrap_model_request(
        self,
        ctx: RunContext[object],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        del ctx
        settings = request_context.model_settings or {}
        level = _RequestEffort.model_validate(settings).level
        if level is not None:
            trace.get_current_span().set_attribute(_REASONING_EFFORT_ATTRIBUTE, level)
        return await handler(request_context)


class _Installed:
    """The providers in force for this process, and whether content is exported."""

    def __init__(self) -> None:
        self.tracer_provider: TracerProvider | None = None
        self.meter_provider: MeterProvider | None = None
        self.include_content = False

    def tracer(self) -> trace.Tracer:
        return trace.get_tracer(_TRACER_NAME, tracer_provider=self.tracer_provider)


_installed = _Installed()


def otlp_exporter_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """``OTEL_EXPORTER_OTLP_HEADERS``, joined by the headers the host adds."""
    named = parse_env_headers(
        _OtlpEnvironment().otel_exporter_otlp_headers, liberal=True
    )
    added = {name.lower(): value for name, value in (extra or {}).items()}
    return {**named, **added}


def install_tracer_provider(provider: TracerProvider, *, include_content: bool) -> None:
    """Open the runtime's spans and every agent run's spans on this provider."""
    provider.add_span_processor(_TraceIdentity())
    _installed.tracer_provider = provider
    _installed.include_content = include_content
    Agent.instrument_all(
        InstrumentationSettings(
            tracer_provider=provider, include_content=include_content
        ),
    )


def reset_tracer_provider() -> None:
    """Forget the installed provider and stop instrumenting agent runs."""
    _installed.tracer_provider = None
    _installed.include_content = False
    Agent.instrument_all(instrument=False)


def install_observability(
    *,
    service_name: str,
    service_version: str,
    environment: str,
    include_content: bool,
    exporter_headers: Mapping[str, str] | None = None,
    engine: AsyncEngine | None = None,
) -> bool:
    """Export this process's traces to the OTLP endpoint the environment names.

    Returns whether a provider was installed. Metrics export only when
    ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`` is set.
    """
    otlp = _OtlpEnvironment()
    if not otlp.exports_traces:
        logger.info("Tracing off: no OTLP endpoint is set")
        return False
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": environment,
            "service.instance.id": str(uuid4()),
        },
    )
    provider = TracerProvider(resource=resource, sampler=traced_roots_sampler())
    exporter = OTLPSpanExporter(headers=otlp_exporter_headers(exporter_headers) or None)
    provider.add_span_processor(BatchSpanProcessor(PricedSpanExporter(exporter)))
    trace.set_tracer_provider(provider)
    install_tracer_provider(provider, include_content=include_content)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    HTTPX2ClientInstrumentor().instrument(tracer_provider=provider)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine, tracer_provider=provider
        )
    if otlp.otel_exporter_otlp_metrics_endpoint:
        reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        _installed.meter_provider = MeterProvider(
            resource=resource, metric_readers=[reader]
        )
        install_meter_provider(_installed.meter_provider)
    logger.info("Tracing on", service=service_name, include_content=include_content)
    return True


def shutdown_observability() -> None:
    """Flush and close the providers this process installed."""
    if _installed.meter_provider is not None:
        _installed.meter_provider.shutdown()
        _installed.meter_provider = None
        reset_meter_provider()
    if _installed.tracer_provider is not None:
        _installed.tracer_provider.shutdown()
        reset_tracer_provider()


def _root_attributes(
    scope: TraceScope, identity: Mapping[str, str]
) -> dict[str, str | tuple[str, ...]]:
    attributes: dict[str, str | tuple[str, ...]] = {
        **identity,
        "langfuse.session.id": str(scope.session_id),
        "langfuse.user.id": str(scope.user_id),
        "langfuse.trace.name": scope.name,
        "langfuse.trace.tags": scope.tags,
    }
    for key, value in scope.metadata.items():
        attributes[f"langfuse.trace.metadata.{key}"] = value
    if _installed.include_content and scope.input_text:
        attributes["langfuse.trace.input"] = scope.input_text
    return attributes


@contextmanager
def traced(scope: TraceScope) -> Iterator[None]:
    """Run the block under a new root span that every span inside it descends from."""
    identity = {"session.id": str(scope.session_id), "user.id": str(scope.user_id)}
    token = _trace_identity.set(identity)
    try:
        with _installed.tracer().start_as_current_span(
            scope.name,
            context=context.Context(),
            attributes=_root_attributes(scope, identity),
        ):
            yield
    finally:
        _trace_identity.reset(token)


def current_trace_id() -> str | None:
    """The 32-hex id of the trace in force, or ``None`` outside a recorded one."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


__all__ = [
    "PricedSpanExporter",
    "ReasoningEffortOnSpan",
    "TraceScope",
    "current_trace_id",
    "install_observability",
    "install_tracer_provider",
    "otlp_exporter_headers",
    "reset_tracer_provider",
    "shutdown_observability",
    "traced",
    "traced_roots_sampler",
]

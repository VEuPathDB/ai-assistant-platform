"""What a probe saw. The checks assert on these, and the report publishes them."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from mcp_conformance._wire import WireModel

# The tool-level key a server declares to render its payload as a typed part.
STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"

# The tool-level key a server declares when one call needs more than the
# source's default budget.
MAX_CALL_SECONDS_META_KEY = "org.veupathdb.assistant/maxCallSeconds"


class PropertySchema(WireModel):
    """One property of a tool's input schema, as far as a probe reads it."""

    type: str | list[str] = ""

    @property
    def declared_types(self) -> tuple[str, ...]:
        return (self.type,) if isinstance(self.type, str) else tuple(self.type)


class InputSchemaView(WireModel):
    """A tool's ``inputSchema``, read for its shape and its required fields."""

    type: str = ""
    properties: dict[str, PropertySchema] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class AnnotationView(WireModel):
    """The four hints the approval predicate and the scan level read."""

    readOnlyHint: bool | None = None
    destructiveHint: bool | None = None
    idempotentHint: bool | None = None
    openWorldHint: bool | None = None


class StreamPartDeclaration(WireModel):
    """What a tool claims its structured payload renders as."""

    kind: str = ""
    version: int = 0


class ToolRecord(WireModel):
    """One row of ``tools/list``, kept in the shape the server sent it."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")

    @property
    def schema_view(self) -> InputSchemaView:
        return InputSchemaView.model_validate(self.input_schema)

    @property
    def annotation(self) -> AnnotationView:
        return AnnotationView.model_validate(self.annotations or {})

    @property
    def stream_part(self) -> StreamPartDeclaration | None:
        declared = (self.meta or {}).get(STREAM_PART_META_KEY)
        if declared is None:
            return None
        return StreamPartDeclaration.model_validate(declared)

    @property
    def declared_max_call_seconds(self) -> float | None:
        declared = (self.meta or {}).get(MAX_CALL_SECONDS_META_KEY)
        if declared is None:
            return None
        return float(declared)


class ServerInfo(WireModel):
    name: str = ""
    version: str = ""


class ToolsCapability(WireModel):
    listChanged: bool | None = None


class ServerCapabilities(WireModel):
    tools: ToolsCapability | None = None


class ServerRecord(WireModel):
    """The ``initialize`` result, read for what the report must name."""

    protocol_version: str = ""
    instructions: str | None = None
    server_info: ServerInfo = ServerInfo()
    capabilities: ServerCapabilities = ServerCapabilities()

    @property
    def name(self) -> str:
        return self.server_info.name

    @property
    def version(self) -> str:
        return self.server_info.version

    @property
    def tools_list_changed(self) -> bool | None:
        if self.capabilities.tools is None:
            return None
        return self.capabilities.tools.listChanged


class CallOutcome(WireModel):
    """What one call produced: a result, a tool error, or a raised error."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raised: str | None = None
    is_error: bool | None = None
    text: str = ""
    structured: dict[str, Any] | None = None
    seconds: float = 0.0

    @property
    def returned(self) -> bool:
        return self.raised is None

    @property
    def evidence_text(self) -> str:
        return self.raised or self.text


class BadArgumentProbe(WireModel):
    """One tool called with a value its own schema refuses."""

    tool: str
    field: str
    outcome: CallOutcome


class RawAnswer(WireModel):
    """What the transport answered a request that carried no credential."""

    status: int
    www_authenticate: str = ""
    body: str = ""


class IsolationEvidence(WireModel):
    """One resource, read by the identity that owns it and by one that does not."""

    tool: str
    as_owner: CallOutcome
    as_stranger: CallOutcome


class AuthEvidence(WireModel):
    """Family 2: what a credential buys, and what its absence costs."""

    unauthorized: RawAnswer
    no_credential: CallOutcome
    wrong_credential: CallOutcome
    answers: list[CallOutcome] = Field(default_factory=list)
    isolation: IsolationEvidence | None = None

    @property
    def every_text(self) -> list[str]:
        spoken = [self.unauthorized.www_authenticate, self.unauthorized.body]
        outcomes = [self.no_credential, self.wrong_credential, *self.answers]
        if self.isolation is not None:
            outcomes += [self.isolation.as_owner, self.isolation.as_stranger]
        return spoken + [outcome.evidence_text for outcome in outcomes]


class AccountWindow(WireModel):
    """The account the hook reported, before a call and after it."""

    before: list[str]
    after: list[str]


class RepeatedCall(WireModel):
    """One tool called twice with the same arguments."""

    tool: str
    idempotent: bool
    first: CallOutcome
    second: CallOutcome


class WriteCall(WireModel):
    """One call by a tool that claims not to destroy anything."""

    tool: str
    window: AccountWindow


class AnnotationEvidence(WireModel):
    """Family 3: what the hints claim, measured against the account."""

    repeated: list[RepeatedCall] = Field(default_factory=list)
    read_only_window: AccountWindow | None = None
    non_destructive: WriteCall | None = None


class TimeoutEvidence(WireModel):
    """Family 5: the handshake's latency, and one call driven past its budget."""

    initialize_seconds: float
    slow_tool: str | None = None
    budget_seconds: float | None = None
    slow_call: CallOutcome | None = None
    survivor: CallOutcome | None = None


class ShapeEvidence(WireModel):
    """Family 1: what the server answered ``initialize`` and ``tools/list`` with."""

    server: ServerRecord
    tools: list[ToolRecord]
    initialize_seconds: float


class ErrorEvidence(WireModel):
    """Family 4: what the server answered a bad argument with."""

    probes: list[BadArgumentProbe]


class StabilityEvidence(WireModel):
    """Family 6: the tool list read over two connections that share nothing."""

    first: list[ToolRecord]
    second: list[ToolRecord]

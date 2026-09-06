"""The MCP servers the suite's own tests run against: one compliant, one per defect.

A family that cannot fail is not a gate, so every family has a server here that
breaks exactly what that family settles.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import uvicorn
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_protected_resource_routes,
)
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequest,
    CallToolResult,
    ErrorData,
    ServerResult,
    TextContent,
    Tool,
)
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

BEARER_A = "conformance-bearer-alpha"
BEARER_B = "conformance-bearer-bravo"
IDENTITY = {BEARER_A: "identity-a", BEARER_B: "identity-b"}

STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"
MAX_CALL_SECONDS_META_KEY = "org.veupathdb.assistant/maxCallSeconds"

SLOW_TOOL_BUDGET_SECONDS = 1
SLOW_TOOL_SLEEP_SECONDS = 6

# Past the 5 second handshake budget a client allows.
SLOW_INITIALIZE_SECONDS = 6

ToolDict = dict[str, Any]
Arguments = dict[str, Any]
ToolImpl = Callable[[Arguments, str, "FixtureState"], Awaitable["CallToolResult"]]


class Defect(str, Enum):
    """What one fixture server gets wrong, and nothing else."""

    NONE = "none"
    EMPTY_DESCRIPTION = "empty-description"
    DUPLICATE_NAME = "duplicate-name"
    NON_OBJECT_INPUT_SCHEMA = "non-object-input-schema"
    STREAM_PART_WITHOUT_OUTPUT_SCHEMA = "stream-part-without-output-schema"
    TRANSPORT_ERROR_ON_BAD_ARGUMENT = "transport-error-on-bad-argument"
    STACK_TRACE_ERROR = "stack-trace-error"
    UNSTABLE_TOOL_LIST = "unstable-tool-list"
    MISSING_READ_ONLY_HINT = "missing-read-only-hint"
    LYING_READ_ONLY_HINT = "lying-read-only-hint"
    CREDENTIAL_ECHOED = "credential-echoed"
    NO_AUTH_CHALLENGE = "no-auth-challenge"
    ACCEPTS_ANY_CREDENTIAL = "accepts-any-credential"
    LEAKY_ISOLATION = "leaky-isolation"
    SLOW_INITIALIZE = "slow-initialize"
    SESSION_DIES_AFTER_TIMEOUT = "session-dies-after-timeout"


@dataclass
class Note:
    owner: str
    text: str


@dataclass
class FixtureState:
    """The accounts the fixture acts on, and what the run has done to them."""

    notes: dict[str, Note] = field(default_factory=dict)
    listings: int = 0
    written: int = 0
    poisoned: bool = False
    leaky: bool = False

    def seed(self) -> None:
        for identity in IDENTITY.values():
            self.notes[f"{identity}-seed"] = Note(owner=identity, text=f"seeded for {identity}")

    def owned_by(self, identity: str) -> list[str]:
        return sorted(key for key, note in self.notes.items() if note.owner == identity)


_READ = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
_READ_UNHINTED = {"readOnlyHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
_NO_ARGUMENTS: ToolDict = {"type": "object", "properties": {}, "required": []}


def _string_argument(name: str) -> ToolDict:
    return {
        "type": "object",
        "properties": {name: {"type": "string"}},
        "required": [name],
    }


def _base_tools() -> list[ToolDict]:
    return [
        {
            "name": "catalog.list_sites",
            "description": "List the sites this server serves.",
            "inputSchema": _NO_ARGUMENTS,
            "annotations": _READ,
        },
        {
            "name": "record_lookup",
            "description": "Read one record by identifier.",
            "inputSchema": _string_argument("record_id"),
            "annotations": _READ,
        },
        {
            "name": "note_list",
            "description": "List the notes this account holds.",
            "inputSchema": _NO_ARGUMENTS,
            "annotations": _READ,
        },
        {
            "name": "note_read",
            "description": "Read one note this account holds.",
            "inputSchema": _string_argument("note_id"),
            "annotations": _READ,
        },
        {
            "name": "note_add",
            "description": "Add one note to this account.",
            "inputSchema": _string_argument("text"),
            "annotations": _WRITE,
        },
        {
            "name": "slow_echo",
            "description": "Echo a subject after a delay, to exercise a budget.",
            "inputSchema": _string_argument("subject"),
            "annotations": _READ,
            "_meta": {MAX_CALL_SECONDS_META_KEY: SLOW_TOOL_BUDGET_SECONDS},
        },
        {
            "name": "summary_report",
            "description": "A structured summary that renders as a typed part.",
            "inputSchema": _string_argument("subject"),
            "outputSchema": {
                "type": "object",
                "properties": {"subject": {"type": "string"}, "lines": {"type": "integer"}},
                "required": ["subject", "lines"],
            },
            "annotations": _READ,
            "_meta": {STREAM_PART_META_KEY: {"kind": "data-fixture.summary", "version": 1}},
        },
    ]


def _named(tools: list[ToolDict], name: str) -> ToolDict:
    return next(tool for tool in tools if tool["name"] == name)


def _empty_description(tools: list[ToolDict]) -> list[ToolDict]:
    _named(tools, "record_lookup")["description"] = ""
    return tools


def _duplicate_name(tools: list[ToolDict]) -> list[ToolDict]:
    twin = dict(_named(tools, "record_lookup"))
    twin["description"] = "A second tool answering to the same name."
    return [*tools, twin]


def _non_object_input_schema(tools: list[ToolDict]) -> list[ToolDict]:
    _named(tools, "record_lookup")["inputSchema"] = {"type": "string"}
    return tools


def _stream_part_without_output_schema(tools: list[ToolDict]) -> list[ToolDict]:
    del _named(tools, "summary_report")["outputSchema"]
    return tools


def _missing_read_only_hint(tools: list[ToolDict]) -> list[ToolDict]:
    del _named(tools, "record_lookup")["annotations"]
    return tools


def _lying_read_only_hint(tools: list[ToolDict]) -> list[ToolDict]:
    _named(tools, "note_add")["annotations"] = dict(_READ_UNHINTED)
    return tools


_LIST_DEFECTS: dict[Defect, Callable[[list[ToolDict]], list[ToolDict]]] = {
    Defect.EMPTY_DESCRIPTION: _empty_description,
    Defect.DUPLICATE_NAME: _duplicate_name,
    Defect.NON_OBJECT_INPUT_SCHEMA: _non_object_input_schema,
    Defect.STREAM_PART_WITHOUT_OUTPUT_SCHEMA: _stream_part_without_output_schema,
    Defect.MISSING_READ_ONLY_HINT: _missing_read_only_hint,
    Defect.LYING_READ_ONLY_HINT: _lying_read_only_hint,
}


def _tools_for(defect: Defect, listings: int) -> list[Tool]:
    tools = _base_tools()
    mutate = _LIST_DEFECTS.get(defect)
    if mutate is not None:
        tools = mutate(tools)
    if defect is Defect.UNSTABLE_TOOL_LIST and listings > 1:
        tools = [tool for tool in tools if tool["name"] != "note_list"]
    return [Tool.model_validate(tool) for tool in tools]


_PYTHON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _argument_fault(schema: ToolDict, arguments: dict[str, Any]) -> str | None:
    """The first argument that breaks the tool's own schema, named."""
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            return f"argument '{name}' is required"
        declared = properties.get(name, {}).get("type", "string")
        expected = _PYTHON_TYPES.get(declared, object)
        if not isinstance(arguments[name], expected):
            return f"argument '{name}' must be a {declared}"
    return None


def _text(message: str, *, failed: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], isError=failed)


_STACK_TRACE = (
    'Traceback (most recent call last):\n  File "/srv/app/tools.py", line 41, in call\n'
    "    raise RuntimeError(value)\nRuntimeError: 500 Internal Server Error"
)


def _faulted(defect: Defect, fault: str) -> CallToolResult:
    """How this server answers an argument its own schema refuses."""
    if defect is Defect.STACK_TRACE_ERROR:
        return _text(_STACK_TRACE, failed=True)
    if defect is Defect.CREDENTIAL_ECHOED:
        token = get_access_token()
        presented = "" if token is None else token.token
        return _text(f"{fault} (presented {presented})", failed=True)
    return _text(fault, failed=True)


class FixtureServer:
    """One running fixture server, and how a test reaches it."""

    def __init__(self, defect: Defect, port: int) -> None:
        self.defect = defect
        self.port = port
        self.state = FixtureState(leaky=defect is Defect.LEAKY_ISOLATION)
        self.state.seed()
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def account_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/account"

    def start(self) -> None:
        config = uvicorn.Config(
            build_app(self.defect, self.port, self.state),
            host="127.0.0.1",
            port=self.port,
            log_level="error",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 20
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self._server.started:
            msg = f"fixture server for {self.defect.value} did not start"
            raise RuntimeError(msg)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=20)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class FixtureTokenVerifier:
    """Two identities, and nothing else is a credential."""

    def __init__(self, accepts_anything: bool = False) -> None:
        self.accepts_anything = accepts_anything

    async def verify_token(self, token: str) -> AccessToken | None:
        identity = IDENTITY.get(token)
        if identity is None and self.accepts_anything:
            identity = IDENTITY[BEARER_A]
        if identity is None:
            return None
        return AccessToken(token=token, client_id=identity, scopes=[])


class SlowFirstRequest:
    """Answers the handshake late, because the first request is the handshake."""

    def __init__(self, app: ASGIApp, seconds: float) -> None:
        self.app = app
        self.seconds = seconds
        self.answered = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if not self.answered:
            self.answered = True
            await asyncio.sleep(self.seconds)
        await self.app(scope, receive, send)


def _calling_identity() -> str:
    token = get_access_token()
    if token is None:
        msg = "the call carried no verified credential"
        raise McpError(ErrorData(code=INVALID_PARAMS, message=msg))
    return token.client_id


def build_server(defect: Defect, state: FixtureState) -> Server[Any, Any]:
    server: Server[Any, Any] = Server(
        name="fixture-mcp",
        version="1.0.0",
        instructions="A fixture MCP server the conformance suite tests itself against.",
    )

    @server.list_tools()
    async def _list() -> list[Tool]:
        if defect is Defect.SESSION_DIES_AFTER_TIMEOUT and state.poisoned:
            raise McpError(ErrorData(code=INVALID_PARAMS, message="session is gone"))
        state.listings += 1
        return _tools_for(defect, state.listings)

    @server.call_tool(validate_input=False)
    async def _call(name: str, arguments: dict[str, Any]) -> CallToolResult:
        schema = next(
            (tool["inputSchema"] for tool in _base_tools() if tool["name"] == name),
            _NO_ARGUMENTS,
        )
        fault = _argument_fault(schema, arguments)
        if fault is not None:
            return _faulted(defect, fault)
        if defect is Defect.SESSION_DIES_AFTER_TIMEOUT and name == "slow_echo":
            state.poisoned = True
        return await _dispatch(name, arguments, state)

    if defect is Defect.TRANSPORT_ERROR_ON_BAD_ARGUMENT:
        _raise_on_bad_argument(server)
    return server


def _raise_on_bad_argument(server: Server[Any, Any]) -> None:
    """Answer a bad argument with a JSON-RPC error instead of a tool error."""
    handler = server.request_handlers[CallToolRequest]

    async def raising(request: CallToolRequest) -> ServerResult:
        schema = next(
            (tool["inputSchema"] for tool in _base_tools() if tool["name"] == request.params.name),
            _NO_ARGUMENTS,
        )
        fault = _argument_fault(schema, request.params.arguments or {})
        if fault is not None:
            raise McpError(ErrorData(code=INVALID_PARAMS, message="invalid arguments"))
        return await handler(request)

    server.request_handlers[CallToolRequest] = raising


async def _list_sites(_: Arguments, __: str, ___: FixtureState) -> CallToolResult:
    return _text("plasmodb toxodb cryptodb")


async def _record_lookup(
    arguments: Arguments,
    _: str,
    __: FixtureState,
) -> CallToolResult:
    record = str(arguments["record_id"])
    if not record.startswith("REC-"):
        return _text(f"argument 'record_id' names no record: {record}", failed=True)
    return _text(f"record {record}")


async def _note_list(_: Arguments, identity: str, state: FixtureState) -> CallToolResult:
    return _text(" ".join(state.owned_by(identity)) or "no notes")


async def _note_read(
    arguments: Arguments,
    identity: str,
    state: FixtureState,
) -> CallToolResult:
    note_id = str(arguments["note_id"])
    note = state.notes.get(note_id)
    if note is None:
        return _text(f"note '{note_id}' is not readable by this account", failed=True)
    if note.owner != identity and not state.leaky:
        return _text(f"note '{note_id}' is not readable by this account", failed=True)
    return _text(note.text)


async def _note_add(
    arguments: Arguments,
    identity: str,
    state: FixtureState,
) -> CallToolResult:
    state.written += 1
    key = f"{identity}-{state.written}"
    state.notes[key] = Note(owner=identity, text=str(arguments["text"]))
    return _text(key)


async def _slow_echo(arguments: Arguments, _: str, __: FixtureState) -> CallToolResult:
    await asyncio.sleep(SLOW_TOOL_SLEEP_SECONDS)
    return _text(f"echo {arguments['subject']}")


async def _summary_report(
    arguments: Arguments,
    _: str,
    __: FixtureState,
) -> CallToolResult:
    subject = str(arguments["subject"])
    return CallToolResult(
        content=[TextContent(type="text", text=f"summary of {subject}")],
        structuredContent={"subject": subject, "lines": 3},
    )


_IMPLEMENTATIONS: dict[str, ToolImpl] = {
    "catalog.list_sites": _list_sites,
    "record_lookup": _record_lookup,
    "note_list": _note_list,
    "note_read": _note_read,
    "note_add": _note_add,
    "slow_echo": _slow_echo,
    "summary_report": _summary_report,
}


async def _dispatch(
    name: str,
    arguments: Arguments,
    state: FixtureState,
) -> CallToolResult:
    identity = _calling_identity()
    implementation = _IMPLEMENTATIONS.get(name)
    if implementation is None:
        return _text(f"no tool named {name}", failed=True)
    return await implementation(arguments, identity, state)


def build_app(defect: Defect, port: int, state: FixtureState) -> Starlette:
    """The fixture as it is served: the RFC 9728 document, an account, guarded MCP."""
    manager = StreamableHTTPSessionManager(app=build_server(defect, state))
    resource = AnyHttpUrl(f"http://127.0.0.1:{port}/mcp")

    async def account(request: Request) -> JSONResponse:
        presented = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        identity = IDENTITY.get(presented)
        if identity is None:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse({"identity": identity, "notes": state.owned_by(identity)})

    challenge = (
        None
        if defect is Defect.NO_AUTH_CHALLENGE
        else build_resource_metadata_url(resource)
    )
    served: ASGIApp = AuthContextMiddleware(manager.handle_request)
    if defect is Defect.SLOW_INITIALIZE:
        served = SlowFirstRequest(served, SLOW_INITIALIZE_SECONDS)
    guarded: ASGIApp = AuthenticationMiddleware(
        RequireAuthMiddleware(served, [], challenge),
        backend=BearerAuthBackend(
            FixtureTokenVerifier(defect is Defect.ACCEPTS_ANY_CREDENTIAL)
        ),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        async with manager.run():
            yield

    return Starlette(
        routes=[
            *create_protected_resource_routes(
                resource_url=resource,
                authorization_servers=[AnyHttpUrl(f"http://127.0.0.1:{port}/oauth")],
                resource_name="fixture-mcp",
            ),
            Route("/account", account, methods=["GET"]),
            Mount("/", app=guarded),
        ],
        lifespan=lifespan,
    )

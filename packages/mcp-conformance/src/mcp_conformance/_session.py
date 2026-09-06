"""One streamable-HTTP connection to the server under test, and what it returns."""

from __future__ import annotations

import time
import traceback
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    Implementation,
    TextContent,
)

from mcp_conformance import __version__
from mcp_conformance._evidence import CallOutcome, RawAnswer, ServerRecord, ToolRecord

CLIENT_INFO = Implementation(name="veupathdb-mcp-conformance", version=__version__)

# A connection budget wide enough that a slow server fails on its own budget,
# not on this one.
_CONNECT_SECONDS = 30.0
_READ_SECONDS = 300.0

# The name a listing is recorded under, which no tool may take (SEP-986 bars "/").
_LIST_TOOLS = "tools/list"


def formatted(error: BaseException) -> str:
    """The error and every error it groups, as one block of text."""
    return "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).strip()


@asynccontextmanager
async def open_session(
    endpoint: str,
    bearer: str | None,
    headers: Mapping[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    """Connect, without initializing: family 5 times the handshake itself."""
    sent = dict(headers or {})
    if bearer:
        sent["Authorization"] = f"Bearer {bearer}"
    timeout = httpx.Timeout(_CONNECT_SECONDS, read=_READ_SECONDS)
    async with (
        httpx.AsyncClient(
            headers=sent,
            timeout=timeout,
            follow_redirects=True,
        ) as http_client,
        streamable_http_client(endpoint, http_client=http_client) as streams,
        ClientSession(
            streams[0],
            streams[1],
            client_info=CLIENT_INFO,
        ) as session,
    ):
        yield session


async def initialize_timed(session: ClientSession) -> tuple[ServerRecord, float]:
    """Handshake, and how long it took."""
    started = time.monotonic()
    result = await session.initialize()
    elapsed = time.monotonic() - started
    declared = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    return ServerRecord.model_validate(declared), elapsed


async def list_tool_records(session: ClientSession) -> list[ToolRecord]:
    listed = await session.list_tools()
    return [
        ToolRecord.model_validate(
            tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        for tool in listed.tools
    ]


def result_text(result: CallToolResult) -> str:
    lines: list[str] = []
    for block in result.content:
        match block:
            case TextContent():
                lines.append(block.text)
            case _:
                lines.append(f"<{block.type} content block>")
    return "\n".join(lines)


async def list_recorded(session: ClientSession) -> CallOutcome:
    """A ``tools/list``, recorded the same way a call is: it proves a live session."""
    started = time.monotonic()
    try:
        tools = await list_tool_records(session)
    except Exception as error:
        return CallOutcome(
            tool=_LIST_TOOLS,
            raised=formatted(error),
            seconds=time.monotonic() - started,
        )
    return CallOutcome(
        tool=_LIST_TOOLS,
        is_error=False,
        text=" ".join(tool.name for tool in tools),
        seconds=time.monotonic() - started,
    )


async def attempt_call(
    endpoint: str,
    bearer: str | None,
    tool: str,
    arguments: dict[str, Any],
) -> CallOutcome:
    """One call on a connection of its own, so a refused credential is visible."""
    started = time.monotonic()
    try:
        async with open_session(endpoint, bearer) as session:
            await session.initialize()
            return await call_recorded(session, tool, arguments)
    except Exception as error:
        return CallOutcome(
            tool=tool,
            arguments=arguments,
            raised=formatted(error),
            seconds=time.monotonic() - started,
        )


async def unauthorized_answer(endpoint: str) -> RawAnswer:
    """What the transport answers an uncredentialed request, headers included."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO.model_dump(mode="json"),
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=_CONNECT_SECONDS) as client:
        answer = await client.post(endpoint, json=body, headers=headers)
    return RawAnswer(
        status=answer.status_code,
        www_authenticate=answer.headers.get("www-authenticate", ""),
        body=answer.text[:2000],
    )


async def call_recorded(
    session: ClientSession,
    tool: str,
    arguments: dict[str, Any],
    budget_seconds: float | None = None,
) -> CallOutcome:
    """Call a tool and record what came back, including a raised error."""
    budget = None if budget_seconds is None else timedelta(seconds=budget_seconds)
    started = time.monotonic()
    try:
        result = await session.call_tool(tool, arguments, read_timeout_seconds=budget)
    except Exception as error:
        return CallOutcome(
            tool=tool,
            arguments=arguments,
            raised=formatted(error),
            seconds=time.monotonic() - started,
        )
    return CallOutcome(
        tool=tool,
        arguments=arguments,
        is_error=result.isError,
        text=result_text(result),
        structured=result.structuredContent,
        seconds=time.monotonic() - started,
    )

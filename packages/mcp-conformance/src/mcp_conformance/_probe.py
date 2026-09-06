"""The calls each family needs, run once and recorded as evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from mcp_conformance._evidence import (
    AccountWindow,
    AnnotationEvidence,
    AuthEvidence,
    BadArgumentProbe,
    ErrorEvidence,
    IsolationEvidence,
    RepeatedCall,
    ShapeEvidence,
    StabilityEvidence,
    TimeoutEvidence,
    ToolRecord,
    WriteCall,
)
from mcp_conformance._options import ConformanceTarget
from mcp_conformance._session import (
    attempt_call,
    call_recorded,
    initialize_timed,
    list_recorded,
    list_tool_records,
    open_session,
    unauthorized_answer,
)

# What the operator's harness answers when the suite asks what this account
# holds. The identifiers are the server's own; the suite only compares them.
AccountSnapshot = Callable[[], Awaitable[Sequence[str]]]

# An object where the schema declares a scalar: refused by every validator, and
# it names one field rather than the whole payload.
BAD_ARGUMENT_VALUE = {"veupathdbMcpConformance": "a value this schema refuses"}

# A credential no server issued. It travels only to be refused.
WRONG_CREDENTIAL = "veupathdb-mcp-conformance-invalid-credential"

# The name the refusal probe uses when the server offers no tool to name.
NO_TOOL = "conformance.no_tool_offered"

_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})


def bad_argument_cases(tools: list[ToolRecord]) -> list[tuple[str, str]]:
    """One (tool, field) per read-only tool that requires a scalar argument.

    Only a tool that claims to read is probed, because the probe exists to find
    out what a server does when its own validation is broken.
    """
    cases: list[tuple[str, str]] = []
    for tool in tools:
        if tool.annotation.readOnlyHint is not True:
            continue
        view = tool.schema_view
        for name in view.required:
            if name in view.properties and _SCALAR_TYPES.intersection(
                view.properties[name].declared_types
            ):
                cases.append((tool.name, name))
                break
    return cases


def arguments_for(
    target: ConformanceTarget,
    tool: ToolRecord,
) -> dict[str, Any] | None:
    """The arguments a call may use, or None when the runner named none."""
    if tool.name in target.sample_arguments:
        return dict(target.sample_arguments[tool.name])
    return {} if not tool.schema_view.required else None


def callable_tools(
    target: ConformanceTarget,
    tools: list[ToolRecord],
) -> list[tuple[ToolRecord, dict[str, Any]]]:
    pairs = ((tool, arguments_for(target, tool)) for tool in tools)
    return [(tool, args) for tool, args in pairs if args is not None]


def _read_only(tools: list[ToolRecord]) -> list[ToolRecord]:
    return [tool for tool in tools if tool.annotation.readOnlyHint is True]


def budget_for(target: ConformanceTarget, tool: ToolRecord) -> float:
    """The budget a call is held to: the tool's own, or the source's default."""
    declared = tool.declared_max_call_seconds
    return target.max_call_seconds if declared is None else declared


def _refusal_target(
    target: ConformanceTarget,
    tools: list[ToolRecord],
) -> tuple[str, dict[str, Any]]:
    """The call the uncredentialed attempts make. Its arguments never matter."""
    readable = callable_tools(target, _read_only(tools))
    if readable:
        return readable[0][0].name, readable[0][1]
    return (tools[0].name, {}) if tools else (NO_TOOL, {})


async def probe_shape(target: ConformanceTarget) -> ShapeEvidence:
    async with open_session(target.endpoint, target.bearer) as session:
        server, seconds = await initialize_timed(session)
        tools = await list_tool_records(session)
    return ShapeEvidence(server=server, tools=tools, initialize_seconds=seconds)


async def probe_errors(
    target: ConformanceTarget,
    tools: list[ToolRecord],
) -> ErrorEvidence:
    probes: list[BadArgumentProbe] = []
    cases = bad_argument_cases(tools)
    if not cases:
        return ErrorEvidence(probes=probes)
    async with open_session(target.endpoint, target.bearer) as session:
        await session.initialize()
        for tool, field in cases:
            outcome = await call_recorded(session, tool, {field: BAD_ARGUMENT_VALUE})
            probes.append(BadArgumentProbe(tool=tool, field=field, outcome=outcome))
    return ErrorEvidence(probes=probes)


async def probe_auth(
    target: ConformanceTarget,
    tools: list[ToolRecord],
) -> AuthEvidence:
    tool, arguments = _refusal_target(target, tools)
    unauthorized = await unauthorized_answer(target.endpoint)
    no_credential = await attempt_call(target.endpoint, None, tool, arguments)
    wrong = await attempt_call(target.endpoint, WRONG_CREDENTIAL, tool, arguments)
    answers = [await attempt_call(target.endpoint, target.bearer, tool, arguments)]
    cases = bad_argument_cases(tools)
    if cases:
        named, field = cases[0]
        answers.append(
            await attempt_call(
                target.endpoint,
                target.bearer,
                named,
                {field: BAD_ARGUMENT_VALUE},
            )
        )
    return AuthEvidence(
        unauthorized=unauthorized,
        no_credential=no_credential,
        wrong_credential=wrong,
        answers=answers,
        isolation=await _probe_isolation(target),
    )


async def _probe_isolation(target: ConformanceTarget) -> IsolationEvidence | None:
    """Read one resource of the second identity, as that identity and as the first."""
    if target.second_bearer is None or target.isolation_tool is None:
        return None
    arguments = dict(target.sample_arguments.get(target.isolation_tool, {}))
    return IsolationEvidence(
        tool=target.isolation_tool,
        as_owner=await attempt_call(
            target.endpoint,
            target.second_bearer,
            target.isolation_tool,
            arguments,
        ),
        as_stranger=await attempt_call(
            target.endpoint,
            target.bearer,
            target.isolation_tool,
            arguments,
        ),
    )


async def probe_annotations(
    target: ConformanceTarget,
    tools: list[ToolRecord],
    account: AccountSnapshot | None,
) -> AnnotationEvidence:
    repeated: list[RepeatedCall] = []
    window = None
    readable = callable_tools(target, _read_only(tools))
    if readable:
        before = None if account is None else list(await account())
        async with open_session(target.endpoint, target.bearer) as session:
            await session.initialize()
            for tool, arguments in readable:
                budget = budget_for(target, tool)
                repeated.append(
                    RepeatedCall(
                        tool=tool.name,
                        idempotent=tool.annotation.idempotentHint is True,
                        first=await call_recorded(session, tool.name, arguments, budget),
                        second=await call_recorded(session, tool.name, arguments, budget),
                    )
                )
        if before is not None and account is not None:
            window = AccountWindow(before=before, after=list(await account()))
    return AnnotationEvidence(
        repeated=repeated,
        read_only_window=window,
        non_destructive=await _probe_non_destructive(target, tools, account),
    )


def _non_destructive_candidates(
    target: ConformanceTarget,
    tools: list[ToolRecord],
) -> list[ToolRecord]:
    """A write the runner named arguments for. Nothing else is called."""
    return [
        tool
        for tool in tools
        if tool.annotation.readOnlyHint is False
        and tool.annotation.destructiveHint is False
        and tool.name in target.sample_arguments
    ]


async def _probe_non_destructive(
    target: ConformanceTarget,
    tools: list[ToolRecord],
    account: AccountSnapshot | None,
) -> WriteCall | None:
    candidates = _non_destructive_candidates(target, tools)
    if account is None or not candidates:
        return None
    tool = candidates[0]
    before = list(await account())
    await attempt_call(
        target.endpoint,
        target.bearer,
        tool.name,
        dict(target.sample_arguments[tool.name]),
    )
    return WriteCall(
        tool=tool.name,
        window=AccountWindow(before=before, after=list(await account())),
    )


async def probe_timeouts(
    target: ConformanceTarget,
    tools: list[ToolRecord],
    initialize_seconds: float,
) -> TimeoutEvidence:
    if target.slow_tool is None:
        return TimeoutEvidence(initialize_seconds=initialize_seconds)
    declared = [tool for tool in tools if tool.name == target.slow_tool]
    budget = budget_for(target, declared[0]) if declared else target.max_call_seconds
    arguments = dict(target.sample_arguments.get(target.slow_tool, {}))
    async with open_session(target.endpoint, target.bearer) as session:
        await session.initialize()
        slow = await call_recorded(session, target.slow_tool, arguments, budget)
        survivor = await list_recorded(session)
    return TimeoutEvidence(
        initialize_seconds=initialize_seconds,
        slow_tool=target.slow_tool,
        budget_seconds=budget,
        slow_call=slow,
        survivor=survivor,
    )


async def probe_stability(target: ConformanceTarget) -> StabilityEvidence:
    """Two connections that share no session id, no cache and no client."""
    async with open_session(target.endpoint, target.bearer) as session:
        await session.initialize()
        first = await list_tool_records(session)
    async with open_session(target.endpoint, target.bearer) as session:
        await session.initialize()
        second = await list_tool_records(session)
    return StabilityEvidence(first=first, second=second)

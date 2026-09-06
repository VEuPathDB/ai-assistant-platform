"""A synthetic assistant whose tools arrive from an in-process MCP server.

Every turn resolves its own sources, builds its agent from them, and closes
them again, which is the lifecycle a per-user credential forces.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset, WrapperToolset
from pydantic_ai.ui.vercel_ai.request_types import ToolApprovalResponded
from tests.mcp_server import SENTINEL_TOKEN, build_tool_server
from tests.synthetic import (
    TurnOutcome,
    TurnRequest,
    UsageLedger,
    build_context,
    drive_turn,
    synthetic_graph,
    synthetic_tool_sources,
)

from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.graph.runtime import TurnContext
from assistant_core.mcp.admission import AdmissionRecord, AdmittedSources
from assistant_core.mcp.resolution import ResolvedToolSources
from assistant_core.mcp.untrusted import OutputScan, ScanVerdict
from assistant_core.spec import AssistantSpec

UNREACHABLE_SOURCE_ID = "unreachable-server"
UNREACHABLE_SOURCE_NAME = "offline"
UNREACHABLE_ENDPOINT = "http://offline.invalid/mcp"


@dataclass
class ScanLog:
    """A guard hook that records what it read, and may replace it."""

    replacement: str = ""
    seen: list[str] = field(default_factory=list)

    async def __call__(self, text: str) -> ScanVerdict:
        self.seen.append(text)
        return ScanVerdict(text=self.replacement or text)


@dataclass
class RefusingToolset(WrapperToolset[Any]):
    """A source whose session cannot be opened."""

    async def __aenter__(self) -> Any:
        msg = "the server refused the connection"
        raise ConnectionError(msg)


@dataclass
class McpRuntime:
    """One thread whose assistant declares the in-process catalog server."""

    spec: AssistantSpec
    checkpointer: AsyncPostgresSaver
    ledger: UsageLedger
    conversation_id: UUID
    user_id: UUID
    admitted: AdmittedSources
    scan: OutputScan
    transports: list[MCPToolset[Any]] = field(default_factory=list)
    handed: list[str | None] = field(default_factory=list)
    contexts: list[TurnContext] = field(default_factory=list)
    # The session state at each turn's own boundaries, outside every agent run.
    open_before_the_agent_ran: list[bool] = field(default_factory=list)
    open_after_the_agent_ran: list[bool] = field(default_factory=list)

    def _credential(self, record: AdmissionRecord) -> str | None:
        del record
        return SENTINEL_TOKEN

    def _build(
        self,
        record: AdmissionRecord,
        credential: str | None,
    ) -> AbstractToolset[Any]:
        self.handed.append(credential)
        if record.source_id == UNREACHABLE_SOURCE_ID:
            return RefusingToolset(FunctionToolset[Any]())
        toolset: MCPToolset[Any] = MCPToolset(build_tool_server())
        self.transports.append(toolset)
        return toolset

    def sources(self) -> ResolvedToolSources:
        return ResolvedToolSources(
            declarations=self.spec.tool_sources,
            admitted=self.admitted,
            credential=self._credential,
            scan=self.scan,
            build_toolset=self._build,
        )

    async def run(
        self,
        prompt: str = "",
        *,
        is_resume: bool = False,
        approval_responses: dict[str, ToolApprovalResponded] | None = None,
    ) -> TurnOutcome:
        """Resolve this turn's sources, drive the turn, then close them."""
        async with self.sources() as resolved:
            context = await build_context(
                self.spec,
                user_id=self.user_id,
                tool_sources=resolved.by_name,
            )
            self.contexts.append(context)
            graph = synthetic_graph(
                checkpointer=self.checkpointer,
                ledger=self.ledger,
                toolsets=tuple(synthetic_tool_sources(context).values()),
            )
            self.open_before_the_agent_ran.append(self._session_open())
            outcome = await drive_turn(
                TurnRequest(
                    spec=self.spec,
                    graph=graph,
                    writer=ChatEventWriter(
                        conversation_id=self.conversation_id,
                        turn_id=uuid4(),
                    ),
                    context=context,
                    conversation_id=self.conversation_id,
                    user_id=self.user_id,
                    prompt=prompt,
                    is_resume=is_resume,
                    approval_responses=approval_responses or {},
                ),
            )
            self.open_after_the_agent_ran.append(self._session_open())
            return outcome

    def _session_open(self) -> bool:
        return bool(self.transports) and self.transports[-1].is_running

    async def answer_approval(
        self,
        tool_call_id: str,
        *,
        approved: bool,
    ) -> TurnOutcome:
        """Drive the turn that carries the user's answer to an approval card."""
        return await self.run(
            is_resume=True,
            approval_responses={
                tool_call_id: ToolApprovalResponded(
                    id=tool_call_id,
                    approved=approved,
                    reason=None,
                ),
            },
        )

    async def state(self) -> dict[str, Any]:
        """Everything the thread's checkpoint holds."""
        graph = synthetic_graph(checkpointer=self.checkpointer, ledger=self.ledger)
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": str(self.conversation_id)}},
        )
        return dict(snapshot.values)


type RuntimeFactory = Callable[..., Awaitable[McpRuntime]]


def unreachable_record() -> AdmissionRecord:
    """An admitted server nothing answers for."""
    return AdmissionRecord(
        source_id=UNREACHABLE_SOURCE_ID,
        endpoint=UNREACHABLE_ENDPOINT,
        part_namespace=UNREACHABLE_SOURCE_NAME,
    )

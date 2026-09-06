"""One turn's tool sources: built, wrapped, entered and closed with the turn.

An `MCPToolset` fixes its credential when it is constructed, so a per-user
credential means a session that opens and closes inside one turn.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset

from assistant_core.mcp.admission import (
    AdmissionRecord,
    AdmittedSources,
    get_admitted_sources,
)
from assistant_core.mcp.approval import build_approval_predicate
from assistant_core.mcp.declaration import (
    ToolSourceDeclaration,
    ToolSourceDeclarations,
)
from assistant_core.mcp.untrusted import OutputScan, pass_through_scan
from assistant_core.mcp.wrapping import wrap_source
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

# Answers with the credential this deployment holds for one admitted server.
type CredentialProvider = Callable[[AdmissionRecord], str | None]

# Where an endpoint becomes a connection, and the only place a credential
# appears.
type ToolsetBuilder = Callable[
    [AdmissionRecord, str | None],
    AbstractToolset[Any],
]

_UNADMITTED = "the deployment admits no such source"


class ToolSourceUnavailableError(RuntimeError):
    """A source the assistant declared as required did not resolve."""


def build_mcp_toolset(
    record: AdmissionRecord,
    credential: str | None,
) -> MCPToolset[Any]:
    """Build the transport for one admitted server."""
    headers = None if credential is None else {"Authorization": f"Bearer {credential}"}
    return MCPToolset(
        record.endpoint,
        headers=headers,
        read_timeout=record.max_call_seconds,
    )


@dataclass(kw_only=True)
class ResolvedToolSources:
    """The wrapped toolsets one turn may use, live only inside its scope."""

    declarations: ToolSourceDeclarations
    credential: CredentialProvider
    scan: OutputScan = pass_through_scan
    # The host installs the admitted set once, so a turn names no server.
    admitted: AdmittedSources = field(default_factory=get_admitted_sources)
    build_toolset: ToolsetBuilder = build_mcp_toolset
    by_name: dict[str, AbstractToolset[Any]] = field(default_factory=dict, init=False)
    _sessions: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)

    async def __aenter__(self) -> Self:
        await self._sessions.__aenter__()
        try:
            for declaration in self.declarations:
                await self._open(declaration)
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        self.by_name.clear()
        await self._sessions.aclose()

    async def _open(self, declaration: ToolSourceDeclaration) -> None:
        record = self.admitted.resolve(declaration.source_id)
        if record is None:
            logger.warning(
                "Tool source did not resolve",
                tool_source=declaration.name,
                source_id=declaration.source_id,
                reason=_UNADMITTED,
            )
            self._refuse_if_required(declaration, _UNADMITTED)
            return
        toolset = wrap_source(
            self.build_toolset(record, self._credential_for(record)),
            admitted=record,
            declaration=declaration,
            predicate=build_approval_predicate(record, declaration),
            scan=self.scan,
        )
        try:
            await self._sessions.enter_async_context(toolset)
        except Exception as exc:
            logger.exception(
                "Tool source did not resolve",
                tool_source=declaration.name,
                source_id=declaration.source_id,
            )
            self._refuse_if_required(declaration, f"{type(exc).__name__}: {exc}", exc)
            return
        self.by_name[declaration.name] = toolset

    def _credential_for(self, record: AdmissionRecord) -> str | None:
        if record.credential_mode == "none":
            return None
        return self.credential(record)

    def _refuse_if_required(
        self,
        declaration: ToolSourceDeclaration,
        reason: str,
        cause: Exception | None = None,
    ) -> None:
        """Refuse the turn when the assistant cannot run without this source."""
        if not declaration.required:
            return
        msg = f"required tool source {declaration.name!r} did not resolve: {reason}"
        raise ToolSourceUnavailableError(msg) from cause


__all__ = [
    "CredentialProvider",
    "ResolvedToolSources",
    "ToolSourceUnavailableError",
    "ToolsetBuilder",
    "build_mcp_toolset",
]

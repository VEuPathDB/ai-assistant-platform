"""Resolution turns declarations into live toolsets, and closes them again.

Every source here is the in-process server or a stub, so the suite opens no
socket.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset, WrapperToolset
from tests.mcp_runtime import RefusingToolset
from tests.mcp_server import (
    IN_PROCESS_ENDPOINT,
    SENTINEL_TOKEN,
    SOURCE_ID,
    SOURCE_NAME,
    build_tool_server,
    catalog_admitted,
    catalog_declaration,
    catalog_record,
)

from assistant_core.mcp.admission import (
    AdmissionRecord,
    AdmittedSources,
    install_admitted_sources,
)
from assistant_core.mcp.resolution import (
    ResolvedToolSources,
    ToolSourceUnavailableError,
    build_mcp_toolset,
)
from assistant_core.spec import TurnContextRequest


async def _never_scanned(text: str) -> Any:
    """A scan hook the resolution tests never assert on."""
    del text
    return None


def _no_credential(record: AdmissionRecord) -> str | None:
    del record
    return None


@dataclass
class _Counting(WrapperToolset[Any]):
    """A source that records how often its session opened and closed."""

    entered: int = 0
    exited: int = 0

    async def __aenter__(self) -> Any:
        self.entered += 1
        return await super().__aenter__()

    async def __aexit__(self, *args: Any) -> bool | None:
        self.exited += 1
        return await super().__aexit__(*args)


@dataclass
class _RecordingCredentials:
    """A credential provider that answers with one token and remembers who asked."""

    token: str = SENTINEL_TOKEN
    asked_for: list[str] = field(default_factory=list)

    def __call__(self, record: AdmissionRecord) -> str | None:
        self.asked_for.append(record.source_id)
        return self.token


def _sources(
    declarations: tuple[Any, ...],
    admitted: AdmittedSources,
    **kwargs: Any,
) -> ResolvedToolSources:
    return ResolvedToolSources(
        declarations=declarations,
        admitted=admitted,
        credential=kwargs.pop("credential", _no_credential),
        scan=kwargs.pop("scan", _never_scanned),
        **kwargs,
    )


@pytest.fixture
def host_admits_the_catalog() -> Iterator[None]:
    """Install the admitted set this process reads, and put it back after."""
    install_admitted_sources(catalog_admitted())
    yield
    install_admitted_sources(AdmittedSources())


async def test_the_admitted_set_defaults_to_what_the_host_installed(
    host_admits_the_catalog: None,
) -> None:
    del host_admits_the_catalog

    async with ResolvedToolSources(
        declarations=(catalog_declaration(),),
        credential=_no_credential,
        build_toolset=lambda record, credential: FunctionToolset[Any](),
    ) as resolved:
        assert list(resolved.by_name) == [SOURCE_NAME]


async def test_a_process_that_admits_nothing_resolves_nothing() -> None:
    async with ResolvedToolSources(
        declarations=(catalog_declaration(),),
        credential=_no_credential,
        build_toolset=lambda record, credential: FunctionToolset[Any](),
    ) as resolved:
        assert dict(resolved.by_name) == {}


async def test_a_declared_source_resolves_under_its_local_name() -> None:
    server = build_tool_server()

    async with _sources(
        (catalog_declaration(),),
        catalog_admitted(),
        build_toolset=lambda record, credential: MCPToolset(server),
    ) as resolved:
        assert list(resolved.by_name) == [SOURCE_NAME]


async def test_an_assistant_that_declares_nothing_opens_no_session() -> None:
    built: list[str] = []

    def _build(record: AdmissionRecord, credential: str | None) -> AbstractToolset[Any]:
        built.append(record.source_id)
        return FunctionToolset[Any]()

    async with _sources((), catalog_admitted(), build_toolset=_build) as resolved:
        assert dict(resolved.by_name) == {}

    assert built == []


async def test_an_unadmitted_optional_source_resolves_absent() -> None:
    built: list[str] = []

    def _build(record: AdmissionRecord, credential: str | None) -> AbstractToolset[Any]:
        built.append(record.source_id)
        return FunctionToolset[Any]()

    async with _sources(
        (catalog_declaration(source_id="never-admitted"),),
        catalog_admitted(),
        build_toolset=_build,
    ) as resolved:
        assert dict(resolved.by_name) == {}

    assert built == []


async def test_an_unadmitted_required_source_refuses_the_turn() -> None:
    sources = _sources(
        (catalog_declaration(source_id="never-admitted", required=True),),
        catalog_admitted(),
    )

    with pytest.raises(ToolSourceUnavailableError, match=SOURCE_NAME):
        async with sources:
            pass


async def test_an_optional_source_that_cannot_connect_resolves_absent() -> None:
    async with _sources(
        (catalog_declaration(),),
        catalog_admitted(),
        build_toolset=lambda record, credential: RefusingToolset(
            FunctionToolset[Any]()
        ),
    ) as resolved:
        assert dict(resolved.by_name) == {}


async def test_a_required_source_that_cannot_connect_refuses_the_turn() -> None:
    sources = _sources(
        (catalog_declaration(required=True),),
        catalog_admitted(),
        build_toolset=lambda record, credential: RefusingToolset(
            FunctionToolset[Any]()
        ),
    )

    with pytest.raises(ToolSourceUnavailableError, match=SOURCE_NAME):
        async with sources:
            pass


async def test_a_source_that_resolved_before_a_required_failure_still_closes() -> None:
    counting = _Counting(FunctionToolset[Any]())
    built: list[AbstractToolset[Any]] = [
        counting,
        RefusingToolset(FunctionToolset[Any]()),
    ]
    second = AdmissionRecord(
        source_id="second",
        endpoint=IN_PROCESS_ENDPOINT,
        part_namespace="second",
    )
    admitted = AdmittedSources(records=(catalog_record(), second))
    declarations = (
        catalog_declaration(),
        catalog_declaration(name="second", source_id="second", required=True),
    )

    with pytest.raises(ToolSourceUnavailableError):
        async with _sources(
            declarations,
            admitted,
            build_toolset=lambda record, credential: built.pop(0),
        ):
            pass

    assert (counting.entered, counting.exited) == (1, 1)


async def test_every_resolved_source_is_closed_when_the_scope_ends() -> None:
    server = build_tool_server()
    toolset = MCPToolset(server)

    async with _sources(
        (catalog_declaration(),),
        catalog_admitted(),
        build_toolset=lambda record, credential: toolset,
    ):
        assert toolset.is_running is True

    assert toolset.is_running is False


async def test_a_source_that_carries_no_credential_never_asks_for_one() -> None:
    credentials = _RecordingCredentials()

    async with _sources(
        (catalog_declaration(),),
        catalog_admitted(credential_mode="none"),
        credential=credentials,
        build_toolset=lambda record, credential: FunctionToolset[Any](),
    ):
        pass

    assert credentials.asked_for == []


async def test_a_source_that_acts_as_the_user_asks_for_the_credential() -> None:
    credentials = _RecordingCredentials()
    handed: list[str | None] = []

    def _build(record: AdmissionRecord, credential: str | None) -> AbstractToolset[Any]:
        handed.append(credential)
        return FunctionToolset[Any]()

    async with _sources(
        (catalog_declaration(),),
        catalog_admitted(credential_mode="veupathdb_user"),
        credential=credentials,
        build_toolset=_build,
    ):
        pass

    assert credentials.asked_for == [SOURCE_ID]
    assert handed == [SENTINEL_TOKEN]


def test_the_transport_carries_the_credential_as_a_bearer_header() -> None:
    toolset = build_mcp_toolset(
        catalog_record(credential_mode="veupathdb_user", endpoint=IN_PROCESS_ENDPOINT),
        SENTINEL_TOKEN,
    )

    assert toolset.client.transport.headers == {
        "Authorization": f"Bearer {SENTINEL_TOKEN}",
    }


def test_a_transport_without_a_credential_carries_no_authorization() -> None:
    toolset = build_mcp_toolset(catalog_record(), None)

    assert toolset.client.transport.headers == {}


def test_the_turn_context_request_carries_the_resolved_sources() -> None:
    toolset = FunctionToolset[Any]()

    request = TurnContextRequest(
        conversation=None,
        site_id="synthetic",
        user_id=uuid4(),
        memory_store=None,
        cancel_event=asyncio.Event(),
        phase_models={},
        phase_reasoning={},
        tool_sources={SOURCE_NAME: toolset},
    )

    assert request.tool_sources[SOURCE_NAME] is toolset


def test_a_turn_context_request_defaults_to_no_sources() -> None:
    request = TurnContextRequest(
        conversation=None,
        site_id="synthetic",
        user_id=uuid4(),
        memory_store=None,
        cancel_event=asyncio.Event(),
        phase_models={},
        phase_reasoning={},
    )

    assert dict(request.tool_sources) == {}

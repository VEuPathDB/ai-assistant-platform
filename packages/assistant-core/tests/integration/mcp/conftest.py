"""Threads whose assistant declares the in-process catalog server."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from tests.conftest import seed_thread
from tests.mcp_runtime import (
    UNREACHABLE_SOURCE_ID,
    UNREACHABLE_SOURCE_NAME,
    McpRuntime,
    RuntimeFactory,
    unreachable_record,
)
from tests.mcp_server import catalog_admitted, catalog_declaration
from tests.synthetic import SYNTHETIC_SITE_ID, UsageLedger, synthetic_spec

from assistant_core.conversation.checkpointer import lifespan_checkpointer
from assistant_core.graph.turn_state import TurnState
from assistant_core.mcp.admission import AdmittedSources, CredentialMode
from assistant_core.mcp.declaration import ToolSourceDeclaration
from assistant_core.mcp.untrusted import OutputScan, pass_through_scan


@pytest.fixture(scope="session")
async def checkpointer(patch_app_db_engine: None) -> AsyncIterator[AsyncPostgresSaver]:
    del patch_app_db_engine
    async with lifespan_checkpointer(
        os.environ["DATABASE_URL"],
        checkpoint_types=(TurnState,),
    ) as saver:
        yield saver


@pytest.fixture
def install_mcp(
    checkpointer: AsyncPostgresSaver,
    db_cleaner: None,
    patch_app_db_engine: None,
) -> RuntimeFactory:
    """Install the synthetic assistant with tool sources of its own."""
    del db_cleaner, patch_app_db_engine

    async def _install(
        *,
        credential_mode: CredentialMode = "none",
        scan: OutputScan = pass_through_scan,
        declare_offline_source: bool = False,
    ) -> McpRuntime:
        declarations: tuple[ToolSourceDeclaration, ...] = (catalog_declaration(),)
        records = catalog_admitted(credential_mode=credential_mode).records
        if declare_offline_source:
            declarations = (
                *declarations,
                catalog_declaration(
                    name=UNREACHABLE_SOURCE_NAME,
                    source_id=UNREACHABLE_SOURCE_ID,
                ),
            )
            records = (*records, unreachable_record())
        ledger = UsageLedger()
        conversation_id = uuid4()
        user_id = uuid4()
        await seed_thread(
            conversation_id=conversation_id,
            user_id=user_id,
            site_id=SYNTHETIC_SITE_ID,
        )
        return McpRuntime(
            spec=synthetic_spec(ledger, tool_sources=declarations),
            checkpointer=checkpointer,
            ledger=ledger,
            conversation_id=conversation_id,
            user_id=user_id,
            admitted=AdmittedSources(records=records),
            scan=scan,
        )

    return _install


@pytest.fixture
async def runtime(install_mcp: RuntimeFactory) -> McpRuntime:
    return await install_mcp()

"""What the platform asks about before a tool served over MCP runs."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage

from assistant_core.mcp.admission import AdmissionRecord
from assistant_core.mcp.approval import (
    ToolAnnotationsView,
    build_approval_predicate,
    source_tool_name,
)
from assistant_core.mcp.declaration import ToolSourceDeclaration

ADMITTED = AdmissionRecord(
    source_id="veupathdb-eda",
    endpoint="https://eda.example/mcp",
    part_namespace="eda",
)
ASKS_EVERY_TIME = AdmissionRecord(
    source_id="veupathdb-eda",
    endpoint="https://eda.example/mcp",
    part_namespace="eda",
    approval_policy="always",
)
DECLARATION = ToolSourceDeclaration(name="eda", source_id="veupathdb-eda")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False}


def _ctx() -> RunContext[None]:
    return RunContext[None](deps=None, model=TestModel(), usage=RunUsage())


def _tool_def(annotations: dict[str, Any] | None) -> ToolDefinition:
    return ToolDefinition(
        name="eda_read_thing",
        metadata={"meta": None, "annotations": annotations, "task": False},
    )


def test_the_view_reads_every_hint_and_ignores_the_title() -> None:
    view = ToolAnnotationsView.model_validate(
        {
            "title": "Read a thing",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )

    assert view.readOnlyHint is True
    assert view.destructiveHint is False
    assert view.idempotentHint is True
    assert view.openWorldHint is False


@pytest.mark.parametrize(
    ("annotations", "asks"),
    [
        ({"readOnlyHint": True, "destructiveHint": False}, False),
        ({"readOnlyHint": True}, False),
        ({"readOnlyHint": True, "destructiveHint": True}, True),
        ({"readOnlyHint": False, "destructiveHint": False}, True),
        ({"destructiveHint": True}, True),
        ({"openWorldHint": True}, True),
        ({}, True),
        (None, True),
    ],
)
def test_an_admitted_source_asks_unless_its_tool_declares_itself_read_only(
    annotations: dict[str, Any] | None,
    asks: bool,
) -> None:
    predicate = build_approval_predicate(ADMITTED, DECLARATION)

    assert predicate(_ctx(), _tool_def(annotations), {}) is asks


def test_a_tool_that_carries_no_metadata_at_all_asks() -> None:
    predicate = build_approval_predicate(ADMITTED, DECLARATION)

    assert predicate(_ctx(), ToolDefinition(name="eda_read_thing"), {}) is True


def test_a_source_this_deployment_never_admitted_asks_however_it_annotates() -> None:
    predicate = build_approval_predicate(None, DECLARATION)

    assert predicate(_ctx(), _tool_def(READ_ONLY), {}) is True


def test_an_always_policy_asks_however_the_tool_annotates() -> None:
    predicate = build_approval_predicate(ASKS_EVERY_TIME, DECLARATION)

    assert predicate(_ctx(), _tool_def(READ_ONLY), {}) is True


def test_an_assistant_adds_friction_under_the_name_the_server_uses() -> None:
    declaration = ToolSourceDeclaration(
        name="eda",
        source_id="veupathdb-eda",
        always_approve=["read_thing"],
    )
    predicate = build_approval_predicate(ADMITTED, declaration)

    assert predicate(_ctx(), _tool_def(READ_ONLY), {}) is True


def test_the_prefixed_name_is_not_the_name_an_assistant_declares() -> None:
    declaration = ToolSourceDeclaration(
        name="eda",
        source_id="veupathdb-eda",
        always_approve=["eda_read_thing"],
    )
    predicate = build_approval_predicate(ADMITTED, declaration)

    assert predicate(_ctx(), _tool_def(READ_ONLY), {}) is False


def test_the_source_tool_name_drops_only_its_own_prefix() -> None:
    assert source_tool_name("eda_read_thing", DECLARATION) == "read_thing"
    assert source_tool_name("wdk_read_thing", DECLARATION) == "wdk_read_thing"

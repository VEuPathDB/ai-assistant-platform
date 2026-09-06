"""Family 3: the hints decide whether a call runs without a click, so they are measured.

An absent ``readOnlyHint`` is a failure and not a default: a team that wants its
reads to run silently writes the hint, and this family holds it to the claim.
"""

from __future__ import annotations

import pytest

from mcp_conformance._evidence import (
    AccountWindow,
    AnnotationEvidence,
    RepeatedCall,
    ShapeEvidence,
    WriteCall,
)

_NO_ACCOUNT = (
    "no mcp_account_state hook: what a read-only call left behind is not settled"
)
_NO_WRITE = (
    "no non-destructive tool has sample arguments, so nothing was written to compare"
)
_NO_IDEMPOTENT = "no tool declares idempotentHint, so no repeat can be compared"


@pytest.fixture(scope="session")
def read_only_window(mcp_annotation_evidence: AnnotationEvidence) -> AccountWindow:
    if mcp_annotation_evidence.read_only_window is None:
        pytest.skip(_NO_ACCOUNT)
    return mcp_annotation_evidence.read_only_window


@pytest.fixture(scope="session")
def non_destructive(mcp_annotation_evidence: AnnotationEvidence) -> WriteCall:
    if mcp_annotation_evidence.non_destructive is None:
        pytest.skip(_NO_WRITE)
    return mcp_annotation_evidence.non_destructive


@pytest.fixture(scope="session")
def idempotent(mcp_annotation_evidence: AnnotationEvidence) -> list[RepeatedCall]:
    repeated = [call for call in mcp_annotation_evidence.repeated if call.idempotent]
    if not repeated:
        pytest.skip(_NO_IDEMPOTENT)
    return repeated


def test_every_tool_declares_read_only_hint(mcp_shape_evidence: ShapeEvidence) -> None:
    unhinted = [
        tool.name
        for tool in mcp_shape_evidence.tools
        if tool.annotation.readOnlyHint is None
    ]

    assert unhinted == []


def test_a_read_only_tool_declares_no_destructive_intent(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    contradictory = [
        tool.name
        for tool in mcp_shape_evidence.tools
        if tool.annotation.readOnlyHint is True
        and tool.annotation.destructiveHint is True
    ]

    assert contradictory == []


def test_read_only_calls_leave_the_account_unchanged(
    read_only_window: AccountWindow,
) -> None:
    appeared = sorted(set(read_only_window.after) - set(read_only_window.before))
    vanished = sorted(set(read_only_window.before) - set(read_only_window.after))

    assert (appeared, vanished) == ([], [])


def test_a_non_destructive_call_removes_nothing(non_destructive: WriteCall) -> None:
    vanished = sorted(
        set(non_destructive.window.before) - set(non_destructive.window.after)
    )

    assert vanished == []


def test_an_idempotent_tool_answers_the_same_twice(
    idempotent: list[RepeatedCall],
) -> None:
    differing = [
        call.tool for call in idempotent if call.first.text != call.second.text
    ]

    assert differing == []

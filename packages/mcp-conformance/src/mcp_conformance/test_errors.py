"""Family 4: what a server answers an argument its own schema refuses.

A runtime that converts a tool error into a retry pays one model turn for every
error that does not name the offending field, so the message is the check.
"""

from __future__ import annotations

import pytest

from mcp_conformance._evidence import BadArgumentProbe, ErrorEvidence

_STACK_TRACE_MARKERS = ("Traceback (most recent call last)", "\tat ", "\n  at ")
_TRANSPORT_MARKERS = ("500 Internal Server Error", "502 Bad Gateway")

_NO_CASE = (
    "no read-only tool requires a scalar argument, "
    "so no bad argument can be built from tools/list alone"
)
_NONE_RETURNED = "every bad argument raised, which the transport check already names"


@pytest.fixture(scope="session")
def probes(mcp_error_evidence: ErrorEvidence) -> list[BadArgumentProbe]:
    if not mcp_error_evidence.probes:
        pytest.skip(_NO_CASE)
    return list(mcp_error_evidence.probes)


@pytest.fixture(scope="session")
def returned(probes: list[BadArgumentProbe]) -> list[BadArgumentProbe]:
    answered = [probe for probe in probes if probe.outcome.returned]
    if not answered:
        pytest.skip(_NONE_RETURNED)
    return answered


def test_a_bad_argument_is_a_tool_error_not_a_transport_error(
    probes: list[BadArgumentProbe],
) -> None:
    raised = [
        f"{probe.tool}: {(probe.outcome.raised or '').splitlines()[-1]}"
        for probe in probes
        if not probe.outcome.returned
    ]

    assert raised == []


def test_a_bad_argument_answers_with_is_error(
    returned: list[BadArgumentProbe],
) -> None:
    accepted = [probe.tool for probe in returned if probe.outcome.is_error is not True]

    assert accepted == []


def test_a_tool_error_names_the_offending_field(
    returned: list[BadArgumentProbe],
) -> None:
    unnamed = [
        f"{probe.tool}: {probe.outcome.text[:120]}"
        for probe in returned
        if probe.field not in probe.outcome.text
    ]

    assert unnamed == []


def test_a_tool_error_carries_content_a_model_can_read(
    returned: list[BadArgumentProbe],
) -> None:
    silent = [probe.tool for probe in returned if not probe.outcome.text.strip()]

    assert silent == []


def test_a_tool_error_is_not_a_stack_trace_or_a_transport_failure(
    returned: list[BadArgumentProbe],
) -> None:
    leaked = [
        probe.tool
        for probe in returned
        if any(
            marker in probe.outcome.text
            for marker in (*_STACK_TRACE_MARKERS, *_TRANSPORT_MARKERS)
        )
    ]

    assert leaked == []

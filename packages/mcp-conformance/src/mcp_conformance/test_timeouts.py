"""Family 5: the handshake fits the client's budget, and a slow call does not take the turn with it.

A call that runs past its budget is expected; a turn that dies with it is not.
"""

from __future__ import annotations

import pytest

from mcp_conformance._evidence import CallOutcome, TimeoutEvidence
from mcp_conformance._options import SLOW_TOOL_OPTION

# The client's default handshake budget. A server slower than this never
# connects, whatever its tools do.
INITIALIZE_BUDGET_SECONDS = 5.0

_NO_SLOW_TOOL = f"{SLOW_TOOL_OPTION} names no tool, so no budget is driven past"


@pytest.fixture(scope="session")
def slow_call(mcp_timeout_evidence: TimeoutEvidence) -> CallOutcome:
    if mcp_timeout_evidence.slow_call is None:
        pytest.skip(_NO_SLOW_TOOL)
    return mcp_timeout_evidence.slow_call


@pytest.fixture(scope="session")
def survivor(mcp_timeout_evidence: TimeoutEvidence) -> CallOutcome:
    if mcp_timeout_evidence.survivor is None:
        pytest.skip(_NO_SLOW_TOOL)
    return mcp_timeout_evidence.survivor


def test_the_handshake_answers_inside_the_clients_budget(
    mcp_timeout_evidence: TimeoutEvidence,
) -> None:
    seconds = mcp_timeout_evidence.initialize_seconds

    assert seconds < INITIALIZE_BUDGET_SECONDS


def test_a_call_past_its_budget_times_out_on_the_client(
    slow_call: CallOutcome,
    mcp_timeout_evidence: TimeoutEvidence,
) -> None:
    answered = slow_call.text if slow_call.returned else ""

    assert (slow_call.returned, answered) == (False, "")


def test_the_timeout_fires_at_the_budget_and_not_later(
    slow_call: CallOutcome,
    mcp_timeout_evidence: TimeoutEvidence,
) -> None:
    budget = mcp_timeout_evidence.budget_seconds or 0.0

    assert slow_call.seconds < 2 * budget + 1.0


def test_the_session_survives_a_call_that_timed_out(survivor: CallOutcome) -> None:
    assert survivor.raised is None
    assert survivor.text != ""

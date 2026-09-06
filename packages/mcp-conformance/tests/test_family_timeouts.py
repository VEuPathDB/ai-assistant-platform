"""Family 5 against the fixtures: a call gives up at its budget, the session does not."""

from __future__ import annotations

import json

from conftest import FamilyRunner, ServerFactory, assert_clean_pass, failed_checks
from fixture_server import Defect

MODULE = "test_timeouts"

SLOW = (
    "--mcp-slow-tool",
    "slow_echo",
    "--mcp-sample-args",
    json.dumps({"slow_echo": {"subject": "conformance"}}),
)


def test_a_compliant_server_passes_the_timeout_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    assert_clean_pass(run_family(MODULE, servers(Defect.NONE), *SLOW), checks=4)


def test_without_a_slow_tool_the_budget_checks_are_skipped(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.NONE))

    result.assert_outcomes(passed=1, skipped=3)
    assert result.ret == 0


def test_a_handshake_past_the_budget_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.SLOW_INITIALIZE))

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_the_handshake_answers_inside_the_clients_budget"
    }


def test_a_session_that_dies_with_the_call_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.SESSION_DIES_AFTER_TIMEOUT), *SLOW)

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_the_session_survives_a_call_that_timed_out"
    }
    result.stdout.fnmatch_lines(["*session is gone*"])

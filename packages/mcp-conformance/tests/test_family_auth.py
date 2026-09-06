"""Family 2 against the fixtures: a credential is refused, and never echoed."""

from __future__ import annotations

import json

import pytest
from conftest import FamilyRunner, ServerFactory, failed_checks
from fixture_server import BEARER_B, Defect

MODULE = "test_auth"

ISOLATION = (
    "--mcp-bearer-second",
    BEARER_B,
    "--mcp-isolation-tool",
    "note_read",
    "--mcp-sample-args",
    json.dumps({"note_read": {"note_id": "identity-b-seed"}}),
)


def test_a_compliant_server_passes_the_auth_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.NONE), *ISOLATION)

    result.assert_outcomes(passed=7)
    assert result.ret == 0


def test_without_a_second_identity_isolation_is_skipped_not_passed(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.NONE))

    result.assert_outcomes(passed=5, skipped=2)
    assert result.ret == 0


@pytest.mark.parametrize(
    ("defect", "checks", "named"),
    [
        (
            Defect.NO_AUTH_CHALLENGE,
            {"test_the_challenge_names_the_protected_resource_document"},
            "resource_metadata",
        ),
        (
            Defect.ACCEPTS_ANY_CREDENTIAL,
            {"test_a_call_with_a_wrong_credential_fails_as_a_protocol_error"},
            "cryptodb",
        ),
        (
            Defect.CREDENTIAL_ECHOED,
            {"test_no_credential_appears_in_any_answer"},
            "presented",
        ),
    ],
)
def test_a_planted_defect_fails_the_check_that_owns_it(
    servers: ServerFactory,
    run_family: FamilyRunner,
    defect: Defect,
    checks: set[str],
    named: str,
) -> None:
    result = run_family(MODULE, servers(defect))

    assert result.ret != 0
    assert failed_checks(result) == checks
    result.stdout.fnmatch_lines([f"*{named}*"])


def test_a_leaky_isolation_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.LEAKY_ISOLATION), *ISOLATION)

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_one_identity_cannot_read_another_identity_resource"
    }
    result.stdout.fnmatch_lines(["*seeded for identity-b*"])

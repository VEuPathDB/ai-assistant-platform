"""Family 2: what a credential buys, what its absence costs, and what leaks.

A refusal that arrives as a tool result is a refusal a model can argue with, so
an uncredentialed call must fail as a protocol error. And the credential itself
belongs in one header and nowhere else, least of all in an error a model reads.
"""

from __future__ import annotations

import pytest

from mcp_conformance._evidence import AuthEvidence, IsolationEvidence
from mcp_conformance._options import (
    ISOLATION_TOOL_OPTION,
    SECOND_BEARER_OPTION,
    ConformanceTarget,
)
from mcp_conformance._probe import WRONG_CREDENTIAL

UNAUTHORIZED = 401

# RFC 9728, which MCP 2025-11-25 requires of an HTTP-transport server: the
# challenge names the document that says where a token comes from.
_RESOURCE_METADATA = "resource_metadata"

_NO_ISOLATION = (
    f"{SECOND_BEARER_OPTION} and {ISOLATION_TOOL_OPTION} name no second identity "
    "and no resource it owns, so isolation is not settled"
)


@pytest.fixture(scope="session")
def isolation(mcp_auth_evidence: AuthEvidence) -> IsolationEvidence:
    if mcp_auth_evidence.isolation is None:
        pytest.skip(_NO_ISOLATION)
    return mcp_auth_evidence.isolation


def test_a_call_with_no_credential_fails_as_a_protocol_error(
    mcp_auth_evidence: AuthEvidence,
) -> None:
    outcome = mcp_auth_evidence.no_credential
    answered = outcome.text if outcome.returned else ""

    assert (outcome.returned, answered) == (False, "")


def test_a_call_with_a_wrong_credential_fails_as_a_protocol_error(
    mcp_auth_evidence: AuthEvidence,
) -> None:
    outcome = mcp_auth_evidence.wrong_credential
    answered = outcome.text if outcome.returned else ""

    assert (outcome.returned, answered) == (False, "")


def test_an_uncredentialed_request_is_unauthorized(
    mcp_auth_evidence: AuthEvidence,
) -> None:
    assert mcp_auth_evidence.unauthorized.status == UNAUTHORIZED


def test_the_challenge_names_the_protected_resource_document(
    mcp_auth_evidence: AuthEvidence,
) -> None:
    challenge = mcp_auth_evidence.unauthorized.www_authenticate

    assert _RESOURCE_METADATA in challenge


def test_no_credential_appears_in_any_answer(
    mcp_auth_evidence: AuthEvidence,
    mcp_target: ConformanceTarget,
) -> None:
    leaked = [
        f"{text[:160]}"
        for text in mcp_auth_evidence.every_text
        for credential in (*mcp_target.credentials, WRONG_CREDENTIAL)
        if credential in text
    ]

    assert leaked == []


def test_one_identity_cannot_read_another_identity_resource(
    isolation: IsolationEvidence,
) -> None:
    stranger = isolation.as_stranger
    answered = stranger.text if stranger.is_error is False else ""

    assert (stranger.is_error is False, answered) == (False, "")


def test_the_isolation_case_names_a_resource_that_exists(
    isolation: IsolationEvidence,
) -> None:
    """A refusal proves nothing if the owner cannot read the resource either."""
    owner = isolation.as_owner

    assert (owner.returned, owner.is_error) == (True, False)

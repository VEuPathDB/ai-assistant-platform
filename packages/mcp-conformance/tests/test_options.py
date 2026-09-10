"""What the runner may name: the credentials a deployment could admit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_conformance._options import BEARER_MINIMUM, ConformanceTarget
from mcp_conformance._report import RUN_MINIMUM

ENDPOINT = "http://server/mcp"

ADMITTED = "zq7wvxkj9mqz4wvx7tbn2hgs5rld8fpc"
TOO_SHORT = ADMITTED[:-1]


def test_a_bearer_at_the_minimum_is_a_credential() -> None:
    target = ConformanceTarget(endpoint=ENDPOINT, bearer=ADMITTED)

    assert len(ADMITTED) == BEARER_MINIMUM
    assert [value.get_secret_value() for value in target.credentials] == [ADMITTED]


def test_a_bearer_shorter_than_the_minimum_is_refused() -> None:
    """No deployment admits it, so the suite says so before any check runs."""
    assert len(TOO_SHORT) == BEARER_MINIMUM - 1

    with pytest.raises(ValidationError, match=str(BEARER_MINIMUM)) as refusal:
        ConformanceTarget(endpoint=ENDPOINT, bearer=TOO_SHORT)

    assert TOO_SHORT not in str(refusal.value)


def test_a_second_bearer_shorter_than_the_minimum_is_refused() -> None:
    with pytest.raises(ValidationError, match=str(BEARER_MINIMUM)):
        ConformanceTarget(
            endpoint=ENDPOINT,
            bearer=ADMITTED,
            second_bearer=TOO_SHORT,
        )


def test_an_empty_bearer_reads_as_no_bearer() -> None:
    """An empty secret reaching redact would mark every character of the report."""
    target = ConformanceTarget(endpoint=ENDPOINT, bearer="", second_bearer="")

    assert target.bearer is None
    assert target.second_bearer is None
    assert target.credentials == ()


def test_the_run_floor_is_half_the_bearer_minimum() -> None:
    assert RUN_MINIMUM == BEARER_MINIMUM // 2

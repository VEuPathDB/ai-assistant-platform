"""What the runner may name: the credentials a deployment could admit."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mcp_conformance._options import (
    BEARER_MINIMUM_ENV,
    BEARER_MINIMUM_OPTION,
    DEFAULT_BEARER_MINIMUM,
    ConformanceTarget,
)
from mcp_conformance._report import RUN_MINIMUM
from mcp_conformance.plugin import target_of

ENDPOINT = "http://server/mcp"

ADMITTED = "zq7wvxkj9mqz4wvx7tbn2hgs5rld8fpc"
TOO_SHORT = ADMITTED[:-1]

STRICTER_MINIMUM = 48


class _Config:
    """The options a runner named, in the shape the plugin reads them."""

    def __init__(self, named: dict[str, str]) -> None:
        self.named = named

    def getoption(self, name: str, default: Any = None) -> Any:
        return self.named.get(name, default)


def test_a_bearer_at_the_minimum_is_a_credential() -> None:
    target = ConformanceTarget(endpoint=ENDPOINT, bearer=ADMITTED)

    assert len(ADMITTED) == DEFAULT_BEARER_MINIMUM
    assert [value.get_secret_value() for value in target.credentials] == [ADMITTED]


def test_a_bearer_shorter_than_the_minimum_is_refused() -> None:
    """The deployment admits no such secret, so the suite says so before a session."""
    assert len(TOO_SHORT) == DEFAULT_BEARER_MINIMUM - 1

    with pytest.raises(ValidationError, match=str(DEFAULT_BEARER_MINIMUM)) as refusal:
        ConformanceTarget(endpoint=ENDPOINT, bearer=TOO_SHORT)

    assert TOO_SHORT not in str(refusal.value)


def test_a_second_bearer_shorter_than_the_minimum_is_refused() -> None:
    with pytest.raises(ValidationError, match=str(DEFAULT_BEARER_MINIMUM)):
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


def test_the_run_floor_is_half_the_default_minimum() -> None:
    """The report's floor is the suite's own, so a relaxed target cannot lower it."""
    assert RUN_MINIMUM == DEFAULT_BEARER_MINIMUM // 2


def test_a_target_admits_the_bearer_its_own_deployment_admits() -> None:
    target = ConformanceTarget(
        endpoint=ENDPOINT,
        bearer=TOO_SHORT,
        bearer_minimum=len(TOO_SHORT),
    )

    assert [value.get_secret_value() for value in target.credentials] == [TOO_SHORT]


def test_a_bearer_under_a_stricter_minimum_is_refused() -> None:
    with pytest.raises(ValidationError, match=str(STRICTER_MINIMUM)) as refusal:
        ConformanceTarget(
            endpoint=ENDPOINT,
            bearer=ADMITTED,
            bearer_minimum=STRICTER_MINIMUM,
        )

    assert ADMITTED not in str(refusal.value)


def test_a_target_that_states_no_minimum_holds_the_default() -> None:
    assert ConformanceTarget(endpoint=ENDPOINT).bearer_minimum == DEFAULT_BEARER_MINIMUM


def test_the_runner_names_the_minimum_on_the_command_line() -> None:
    config = _Config({"--mcp-endpoint": ENDPOINT, BEARER_MINIMUM_OPTION: "24"})

    target = target_of(config)

    assert target is not None
    assert target.bearer_minimum == 24


def test_the_minimum_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BEARER_MINIMUM_ENV, "24")
    config = _Config({"--mcp-endpoint": ENDPOINT})

    target = target_of(config)

    assert target is not None
    assert target.bearer_minimum == 24

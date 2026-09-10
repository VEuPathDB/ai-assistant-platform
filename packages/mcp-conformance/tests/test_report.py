"""The admission record: what it says, and what it never carries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FamilyRunner, ServerFactory, account_hook
from fixture_server import BEARER_A, BEARER_B, Defect
from pydantic import SecretStr

from mcp_conformance._options import ConformanceTarget
from mcp_conformance._report import (
    REDACTED,
    RUN_MINIMUM,
    AdmissionReport,
    CheckResult,
    FamilyResult,
    ReportAccumulator,
    ReportTarget,
    redact,
    verdict_of,
)


def _report(pytester: pytest.Pytester) -> dict[str, Any]:
    written = Path(pytester.path) / "report.json"
    parsed: dict[str, Any] = json.loads(written.read_text())
    return parsed


FULLY_CONFIGURED = (
    "-p",
    "account_hook",
    "--mcp-bearer-second",
    BEARER_B,
    "--mcp-isolation-tool",
    "note_read",
    "--mcp-slow-tool",
    "slow_echo",
    "--mcp-sample-args",
    json.dumps(
        {
            "note_read": {"note_id": "identity-b-seed"},
            "note_add": {"text": "written by the conformance suite"},
            "slow_echo": {"subject": "conformance"},
        }
    ),
)


def test_a_fully_configured_green_run_writes_a_passing_report(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    server = servers(Defect.NONE)
    account_hook(pytester, server)

    result = run_family(
        "",
        server,
        *FULLY_CONFIGURED,
        "--mcp-report",
        "report.json",
    )

    assert result.ret == 0
    report = _report(pytester)
    assert report["verdict"] == "pass"
    assert report["target"]["credential"] == "two"
    assert report["server"]["serverInfo"]["name"] == "fixture-mcp"
    assert report["server"]["protocolVersion"] != ""
    assert [family["id"] for family in report["families"]] == [
        "shape",
        "auth",
        "annotations",
        "errors",
        "timeouts",
        "stability",
    ]
    assert all(family["checks"] for family in report["families"])
    assert "record_lookup" in [tool["name"] for tool in report["tools"]]


def test_a_run_that_settles_less_than_it_could_is_incomplete(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    """Every family ran and nothing failed, but seven checks had no evidence."""
    result = run_family("", servers(Defect.NONE), "--mcp-report", "report.json")

    assert result.ret == 0
    report = _report(pytester)
    assert report["verdict"] == "incomplete"
    skipped = [
        check["id"]
        for family in report["families"]
        for check in family["checks"]
        if check["outcome"] == "skipped"
    ]
    assert len(skipped) == 7


def test_a_report_of_one_family_is_incomplete_not_passing(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(
        "test_stability",
        servers(Defect.NONE),
        "--mcp-report",
        "report.json",
    )

    assert result.ret == 0
    assert _report(pytester)["verdict"] == "incomplete"


def test_a_planted_defect_makes_the_report_fail(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(
        "test_shape",
        servers(Defect.EMPTY_DESCRIPTION),
        "--mcp-report",
        "report.json",
    )

    assert result.ret != 0
    report = _report(pytester)
    assert report["verdict"] == "fail"
    failing = [
        check
        for family in report["families"]
        for check in family["checks"]
        if check["outcome"] == "failed"
    ]
    assert [check["id"] for check in failing] == [
        "test_shape.py::test_every_tool_describes_itself"
    ]
    assert "record_lookup" in str(failing[0]["message"])


def test_the_report_never_carries_the_credential(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    server = servers(Defect.CREDENTIAL_ECHOED)
    run_family("", server, "--mcp-report", "report.json")

    written = (Path(pytester.path) / "report.json").read_text()
    assert BEARER_A not in written
    assert REDACTED in written


def test_a_message_that_echoes_the_credential_is_redacted() -> None:
    accumulator = ReportAccumulator(
        target=ReportTarget(endpoint="http://server/mcp", credential="one"),
        credentials=(SecretStr("s3cret-bearer"),),
    )
    nodeid = "src/mcp_conformance/test_shape.py::test_tool_names_are_unique"
    accumulator.assign(nodeid, "test_shape")
    accumulator.record_check(
        nodeid,
        "failed",
        "the server answered with s3cret-bearer in the message",
    )

    rendered = accumulator.build().rendered(accumulator.credentials)

    assert "s3cret-bearer" not in rendered
    assert REDACTED in rendered


def _family(**counts: int) -> FamilyResult:
    checks = [CheckResult(id="test_shape.py::test_x", outcome="passed")]
    return FamilyResult(
        id="shape",
        number=1,
        title="Shape",
        passed=counts.get("passed", 1),
        failed=counts.get("failed", 0),
        skipped=counts.get("skipped", 0),
        checks=checks,
    )


@pytest.mark.parametrize(
    ("families", "verdict"),
    [
        ([_family()], "pass"),
        ([_family(failed=1)], "fail"),
        ([_family(skipped=1)], "incomplete"),
        ([_family(failed=1, skipped=1)], "fail"),
    ],
)
def test_a_skip_is_not_a_pass(families: list[FamilyResult], verdict: str) -> None:
    assert verdict_of(families) == verdict


def test_a_family_that_never_ran_is_not_a_pass() -> None:
    empty = FamilyResult(
        id="errors",
        number=4,
        title="Errors",
        passed=0,
        failed=0,
        skipped=0,
        checks=[],
    )

    assert verdict_of([_family(), empty]) == "incomplete"


def test_the_report_leaves_the_schemas_out_of_its_tool_rows() -> None:
    accumulator = ReportAccumulator()
    report = accumulator.build()

    assert isinstance(report, AdmissionReport)
    assert json.loads(report.rendered(()))["tools"] == []


# Long enough that pytest shortens its repr, and made of no word the run writes
# on its own, so any run of it found in the output is the credential.
LEAKY_BEARER = "zq7wvxkj9mqz4wvx7tbn2hgs5rld8fpc" * 14

_ERRORING_FAMILY = """
import pytest


@pytest.fixture
def deployment(mcp_target):
    raise RuntimeError("the runner named a deployment this check cannot read")


def test_tool_names_are_unique(deployment):
    assert True
"""


def _surviving_runs(text: str, credential: str) -> list[str]:
    """Every run of the credential at the floor length still in the text.

    A longer run contains one of these, so an empty answer is the whole rule.
    """
    return [
        credential[index : index + RUN_MINIMUM]
        for index in range(len(credential) - RUN_MINIMUM + 1)
        if credential[index : index + RUN_MINIMUM] in text
    ]


def test_an_errored_check_carries_no_run_of_the_credential(
    pytester: pytest.Pytester,
) -> None:
    """A fixture that raises renders its locals, and the target is one of them."""
    pytester.makepyfile(test_shape=_ERRORING_FAMILY)

    result = pytester.runpytest_subprocess(
        "test_shape.py",
        "--mcp-endpoint",
        "http://server.invalid/mcp",
        "--mcp-bearer",
        LEAKY_BEARER,
        "--mcp-report",
        "report.json",
        "--showlocals",
        "-p",
        "no:cacheprovider",
    )

    assert result.ret != 0
    written = (Path(pytester.path) / "report.json").read_text()
    assert '"outcome": "error"' in written
    assert _surviving_runs(written, LEAKY_BEARER) == []
    captured = result.stdout.str() + result.stderr.str()
    assert _surviving_runs(captured, LEAKY_BEARER) == []


def test_the_target_reads_its_credential_through_an_accessor_only() -> None:
    target = ConformanceTarget(endpoint="http://server/mcp", bearer=LEAKY_BEARER)

    assert LEAKY_BEARER not in repr(target)
    assert LEAKY_BEARER not in str(target)

    held = target.bearer
    assert held is not None
    assert held.get_secret_value() == LEAKY_BEARER
    assert [value.get_secret_value() for value in target.credentials] == [LEAKY_BEARER]


# Thirty-two characters, the shortest secret a deployment admits.
ADMITTED_BEARER = SecretStr("zq7wvxkj9mqz4wvx7tbn2hgs5rld8fpc")


def test_a_run_of_the_credential_is_redacted_wherever_it_sits() -> None:
    """A shortened repr keeps a head and a tail, and both are the credential."""
    value = ADMITTED_BEARER.get_secret_value()
    text = f"{value[:24]}...{value[-16:]} answered"

    redacted = redact(text, (ADMITTED_BEARER,))

    assert redacted == f"{REDACTED}...{REDACTED} answered"
    assert _surviving_runs(redacted, value) == []


def test_a_run_shorter_than_the_floor_is_left_alone() -> None:
    value = ADMITTED_BEARER.get_secret_value()
    short = f"read {value[: RUN_MINIMUM - 1]} and {value[-(RUN_MINIMUM - 1) :]} only"

    assert redact(short, (ADMITTED_BEARER,)) == short


def test_the_floor_keeps_prose_and_takes_a_sixteen_character_run() -> None:
    """A shared run of fifteen characters is prose; sixteen is the credential."""
    value = ADMITTED_BEARER.get_secret_value()

    prose = f'{{"name": "{value[:15]}-conformance"}}'
    assert redact(prose, (ADMITTED_BEARER,)) == prose

    leading = f"the server answered {value[:16]} to the call"
    assert redact(leading, (ADMITTED_BEARER,)) == (
        f"the server answered {REDACTED} to the call"
    )

    interior = f"the server answered {value[8:24]} to the call"
    assert redact(interior, (ADMITTED_BEARER,)) == (
        f"the server answered {REDACTED} to the call"
    )


def test_a_credential_shorter_than_the_floor_is_taken_out_whole() -> None:
    """The floor holds back runs, never the value itself."""
    credential = SecretStr("zq7wv")

    assert redact("read zq7wv now", (credential,)) == f"read {REDACTED} now"

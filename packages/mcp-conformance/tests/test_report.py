"""The admission record: what it says, and what it never carries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FamilyRunner, ServerFactory, account_hook
from fixture_server import BEARER_A, BEARER_B, Defect

from mcp_conformance._report import (
    REDACTED,
    AdmissionReport,
    CheckResult,
    FamilyResult,
    ReportAccumulator,
    ReportTarget,
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
        credentials=("s3cret-bearer",),
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

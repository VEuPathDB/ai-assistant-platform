"""Family 3 against the fixtures: a hint is measured against the account."""

from __future__ import annotations

import json

import pytest
from conftest import FamilyRunner, ServerFactory, account_hook, failed_checks
from fixture_server import Defect

MODULE = "test_annotations"

WRITE_ARGS = json.dumps({"note_add": {"text": "written by the conformance suite"}})
CONFIGURED = ("-p", "account_hook", "--mcp-sample-args", WRITE_ARGS)


def test_a_compliant_server_passes_the_annotation_family(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    server = servers(Defect.NONE)
    account_hook(pytester, server)

    result = run_family(MODULE, server, *CONFIGURED)

    result.assert_outcomes(passed=5)
    assert result.ret == 0


def test_without_the_account_hook_the_comparisons_are_skipped(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.NONE))

    result.assert_outcomes(passed=3, skipped=2)
    assert result.ret == 0


def test_a_missing_read_only_hint_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.MISSING_READ_ONLY_HINT))

    assert result.ret != 0
    assert failed_checks(result) == {"test_every_tool_declares_read_only_hint"}
    result.stdout.fnmatch_lines(["*record_lookup*"])


def test_a_read_only_hint_that_writes_fails_the_family(
    pytester: pytest.Pytester,
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    server = servers(Defect.LYING_READ_ONLY_HINT)
    account_hook(pytester, server)

    result = run_family(MODULE, server, *CONFIGURED)

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_read_only_calls_leave_the_account_unchanged"
    }
    result.stdout.fnmatch_lines(["*identity-a-*"])

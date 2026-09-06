"""Family 6 against the fixtures: a tool list that drifts between connections fails."""

from __future__ import annotations

from conftest import FamilyRunner, ServerFactory, assert_clean_pass, failed_checks
from fixture_server import Defect

MODULE = "test_stability"


def test_a_compliant_server_passes_the_stability_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    assert_clean_pass(run_family(MODULE, servers(Defect.NONE)), checks=2)


def test_a_tool_list_that_drifts_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.UNSTABLE_TOOL_LIST))

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_the_tool_names_are_the_same_across_two_connections"
    }
    result.stdout.fnmatch_lines(["*note_list*"])

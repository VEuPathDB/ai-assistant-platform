"""Family 4 against the fixtures: a bad argument answers with a named field."""

from __future__ import annotations

from conftest import FamilyRunner, ServerFactory, assert_clean_pass, failed_checks
from fixture_server import Defect

MODULE = "test_errors"


def test_a_compliant_server_passes_the_error_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    assert_clean_pass(run_family(MODULE, servers(Defect.NONE)), checks=5)


def test_a_transport_error_on_a_bad_argument_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.TRANSPORT_ERROR_ON_BAD_ARGUMENT))

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_a_bad_argument_is_a_tool_error_not_a_transport_error"
    }
    result.stdout.fnmatch_lines(["*record_lookup*"])


def test_a_stack_trace_instead_of_a_message_fails_the_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    result = run_family(MODULE, servers(Defect.STACK_TRACE_ERROR))

    assert result.ret != 0
    assert failed_checks(result) == {
        "test_a_tool_error_names_the_offending_field",
        "test_a_tool_error_is_not_a_stack_trace_or_a_transport_failure",
    }

"""Family 1 against the fixtures: green on the compliant server, named on each defect."""

from __future__ import annotations

import pytest
from conftest import FamilyRunner, ServerFactory, assert_clean_pass, failed_checks
from fixture_server import Defect

MODULE = "test_shape"


def test_a_compliant_server_passes_the_shape_family(
    servers: ServerFactory,
    run_family: FamilyRunner,
) -> None:
    assert_clean_pass(run_family(MODULE, servers(Defect.NONE)), checks=9)


@pytest.mark.parametrize(
    ("defect", "checks", "named"),
    [
        (
            Defect.EMPTY_DESCRIPTION,
            {"test_every_tool_describes_itself"},
            "record_lookup",
        ),
        (Defect.DUPLICATE_NAME, {"test_tool_names_are_unique"}, "record_lookup"),
        (
            Defect.NON_OBJECT_INPUT_SCHEMA,
            {"test_every_input_schema_is_an_object_schema"},
            "record_lookup",
        ),
        (
            Defect.STREAM_PART_WITHOUT_OUTPUT_SCHEMA,
            {"test_a_stream_part_tool_declares_an_output_schema"},
            "summary_report",
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

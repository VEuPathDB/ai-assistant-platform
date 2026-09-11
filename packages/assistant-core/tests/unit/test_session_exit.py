"""A run that imported the ONNX runtime leaves with pytest's own status."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SUITE = """
import onnxruntime  # noqa: F401


def test_passes():
    assert True

{failing}
"""

_FAILING = """
def test_fails():
    assert False
"""


@pytest.mark.parametrize(
    ("failing", "expected_code", "expected_summary"),
    [("", 0, "1 passed"), (_FAILING, 1, "1 failed, 1 passed")],
)
async def test_a_run_exits_with_the_status_pytest_computed(
    tmp_path: Path,
    failing: str,
    expected_code: int,
    expected_summary: str,
) -> None:
    """The summary is written before the process leaves on that status."""
    suite = tmp_path / "test_exit_status.py"
    suite.write_text(_SUITE.format(failing=failing))

    run = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pytest",
        str(suite),
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "tests.conftest",
        cwd=Path(__file__).parents[2],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await run.communicate()

    assert run.returncode == expected_code, err.decode()
    assert expected_summary in out.decode()

"""Importing the scanners without the screening packages names the extra."""

from __future__ import annotations

import asyncio
import sys

import pytest

SCREENING_PACKAGES = ("onnxruntime", "tokenizers")

# A child process blocks one package and imports the module. Reloading the
# screening packages in this process leaves their native runtime half built,
# and the interpreter aborts on the way out.
_PROBE = """
import sys

sys.modules[{name!r}] = None
try:
    import assistant_core.capabilities.piguard
except ModuleNotFoundError as caught:
    print(caught)
    print(caught.__cause__)
"""


@pytest.mark.parametrize("absent_package", SCREENING_PACKAGES)
async def test_an_absent_screening_package_names_the_extra(
    absent_package: str,
) -> None:
    """The import error tells a host which extra it did not declare."""
    probe = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _PROBE.format(name=absent_package),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await probe.communicate()

    assert probe.returncode == 0, err.decode()
    said = out.decode().splitlines()
    assert said[0] == "assistant-core[screening] is required to run input screening"
    assert absent_package in said[1]

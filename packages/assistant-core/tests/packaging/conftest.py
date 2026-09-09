"""Builds the distribution once, for every test that reads the built wheel."""

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Ruff trusts an argv of string literals, so every varying value below rides the
# working directory or a file the command names.


@pytest.fixture(scope="session")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("packaging").resolve()
    (work / "project").symlink_to(PROJECT_ROOT)
    subprocess.run(
        ["/usr/bin/env", "uv", "build", "--project", "project", "--out-dir", "dist"],
        cwd=work,
        check=True,
    )
    return work


@pytest.fixture(scope="session")
def built_wheel(workspace: Path) -> Path:
    wheels = sorted((workspace / "dist").glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"
    return wheels[0]

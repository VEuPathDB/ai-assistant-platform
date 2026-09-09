"""The built wheel carries the chain, so an installed host can migrate."""

import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHAIN_SOURCE = PROJECT_ROOT / "src" / "assistant_core" / "alembic"
WHEEL_PREFIX = "assistant_core/alembic/"


@pytest.mark.wheel
def test_the_wheel_holds_every_file_of_the_chain(built_wheel: Path) -> None:
    """The env, the template and every revision are packed, not only the .py files."""
    with zipfile.ZipFile(built_wheel) as archive:
        packed = {
            name.removeprefix(WHEEL_PREFIX)
            for name in archive.namelist()
            if name.startswith(WHEEL_PREFIX)
        }

    written = {
        str(path.relative_to(CHAIN_SOURCE))
        for path in CHAIN_SOURCE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert written <= packed
    assert "env.py" in packed
    assert "script.py.mako" in packed

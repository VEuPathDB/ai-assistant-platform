"""The built wheel carries the wire document, and an installed copy reads it."""

import subprocess
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENT_SOURCE = PROJECT_ROOT / "src" / "assistant_core" / "PROTOCOL.md"
WHEEL_ENTRY = "assistant_core/PROTOCOL.md"

# Ruff trusts an argv of string literals, so every varying value below rides the
# working directory or a file the command names.


@pytest.mark.wheel
def test_the_wheel_holds_the_wire_document(built_wheel: Path) -> None:
    """The document is packed beside the package that serves the wire."""
    with zipfile.ZipFile(built_wheel) as archive:
        packed = archive.read(WHEEL_ENTRY).decode()

    assert packed == DOCUMENT_SOURCE.read_text()


@pytest.mark.wheel
def test_an_installed_copy_reads_the_document(
    workspace: Path,
    built_wheel: Path,
) -> None:
    """An installed interpreter resolves the document beside the package."""
    (workspace / "requirements.txt").write_text(f"{built_wheel}\n")
    subprocess.run(
        ["/usr/bin/env", "uv", "venv", "--python", "3.14", "env"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/env",
            "uv",
            "pip",
            "install",
            "--python",
            "env/bin/python",
            "--requirement",
            "requirements.txt",
        ],
        cwd=workspace,
        check=True,
    )
    (workspace / "read.py").write_text(
        "import assistant_core, pathlib\n"
        "print((pathlib.Path(assistant_core.__file__).parent / 'PROTOCOL.md')"
        ".read_text().splitlines()[0])\n",
    )
    read = subprocess.run(
        ["/usr/bin/env", "env/bin/python", "read.py"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )

    assert read.stdout.strip() == DOCUMENT_SOURCE.read_text().splitlines()[0]

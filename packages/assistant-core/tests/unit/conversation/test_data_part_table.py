"""The data-part table is checked against the builders something here calls.

A kind the runtime's own modules emit, or the reference producer emits, is the
document's to name. A builder whose only caller is a host's code is the host's.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import assistant_core
from assistant_core.conversation.stream_parts.core_parts import (
    register_core_stream_parts,
)
from assistant_core.conversation.stream_parts.registry import StreamPartRegistry

SRC = Path(assistant_core.__file__).parent
PROTOCOL = SRC / "PROTOCOL.md"
BUILDERS = SRC / "graph" / "stream_events.py"
# The assistant the captured examples are recorded from.
REFERENCE_PRODUCER = Path(__file__).parents[2] / "synthetic.py"

_TABLE_KIND = re.compile(r"^\| `([a-z][a-z0-9-]*)` \|", re.MULTILINE)
_DATA_PARTS = re.compile(
    r"<!-- data_parts:begin -->\n(.*?)\n<!-- data_parts:end -->",
    re.DOTALL,
)


def _table_kinds() -> set[str]:
    section = _DATA_PARTS.search(PROTOCOL.read_text())
    assert section is not None, "PROTOCOL.md has no data-part table"
    return set(_TABLE_KIND.findall(section.group(1)))


def _chunk_kind(function: ast.FunctionDef) -> str | None:
    """The kind the ``DataChunk`` this function returns carries."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "DataChunk":
            continue
        for keyword in node.keywords:
            if keyword.arg == "type" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return None


def _builders() -> dict[str, str]:
    """Each builder in the chunk module, by the kind it returns."""
    tree = ast.parse(BUILDERS.read_text())
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        kind = _chunk_kind(node)
        if kind is not None:
            found[node.name] = kind
    return found


def _called_here() -> set[str]:
    """Every function name called by a runtime module or the reference producer."""
    sources = [path for path in SRC.rglob("*.py") if path != BUILDERS]
    sources.append(REFERENCE_PRODUCER)
    called: set[str] = set()
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
    return called


def test_the_builders_carry_a_kind_each() -> None:
    assert len(_builders()) >= 10


def test_the_table_names_every_kind_something_here_emits() -> None:
    called = _called_here()
    emitted = {kind for name, kind in _builders().items() if name in called}

    assert emitted - _table_kinds() == set()


def test_the_core_registry_carries_the_kind_the_scratchpad_emits() -> None:
    registry = StreamPartRegistry()
    register_core_stream_parts(registry)

    assert "data-scratchpad-updated" in registry.kinds()

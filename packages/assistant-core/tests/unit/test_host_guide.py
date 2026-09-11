"""Every runtime name the host guide prints is a name this package has.

The guide is the page a second organisation wires a host from, so a symbol it
names and this package lost is an ImportError in somebody else's deployment.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import re
from dataclasses import dataclass
from pathlib import Path

GUIDE = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "knowledge"
    / "conventions"
    / "embedding-the-runtime-in-a-host.md"
)

# The page names no application: every dotted name below it is under this one.
ROOT = "assistant_core"

# The parts of the runtime a host reaches. A name under any other part is a
# name the page invented.
PARTS = {
    "capabilities",
    "conversation",
    "errors",
    "graph",
    "mcp",
    "persistence",
    "quota",
    "registry",
    "tasks",
}

_CODE_SPAN = re.compile(r"`([^`]+)`", re.DOTALL)


@dataclass(frozen=True)
class _Named:
    """One dotted name the guide prints, with the keywords it passes it."""

    dotted: str
    keywords: tuple[str, ...]


def _dotted(node: ast.expr) -> str | None:
    """The dotted name this expression spells, or None if it spells none."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or not parts:
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _named(span: str) -> _Named | None:
    """The runtime name this code span reads as, or None if it reads as prose."""
    try:
        parsed = ast.parse(span, mode="eval")
    except SyntaxError:
        return None
    node = parsed.body
    keywords: tuple[str, ...] = ()
    if isinstance(node, ast.Call):
        keywords = tuple(word.arg for word in node.keywords if word.arg is not None)
        node = node.func
    dotted = _dotted(node)
    if dotted is None or dotted.split(".")[0] not in PARTS:
        return None
    return _Named(dotted=dotted, keywords=keywords)


def _names() -> list[_Named]:
    text = GUIDE.read_text()
    spans = (" ".join(found.group(1).split()) for found in _CODE_SPAN.finditer(text))
    return [named for named in (_named(span) for span in spans) if named is not None]


def _resolve(dotted: str) -> object:
    """The object this name reaches, importing the modules on the way."""
    current: object = importlib.import_module(ROOT)
    reached = ROOT
    for part in dotted.split("."):
        reached = f"{reached}.{part}"
        try:
            current = getattr(current, part)
        except AttributeError:
            current = importlib.import_module(reached)
    return current


def test_the_guide_names_a_page_that_is_here() -> None:
    assert GUIDE.is_file()


def test_every_name_the_guide_prints_resolves() -> None:
    unresolved: list[str] = []
    for named in _names():
        try:
            _resolve(named.dotted)
        except (AttributeError, ImportError) as refused:
            unresolved.append(f"{named.dotted}: {refused}")

    assert unresolved == []


def test_every_keyword_the_guide_passes_is_a_parameter() -> None:
    unknown: list[str] = []
    for named in _names():
        if not named.keywords:
            continue
        called = _resolve(named.dotted)
        assert callable(called)
        parameters = inspect.signature(called).parameters
        unknown.extend(
            f"{named.dotted}: {word}"
            for word in named.keywords
            if word not in parameters
        )

    assert unknown == []


def test_the_guide_reaches_these_parts_of_the_runtime() -> None:
    """A new part in the page is a new part of the surface a host depends on."""
    reached = {named.dotted.split(".")[0] for named in _names()}

    assert reached == PARTS


def test_the_guide_names_the_call_that_defers_a_turn() -> None:
    """The page is the only place that states the write path, so it is read."""
    named = {found.dotted for found in _names()}

    assert "tasks.chat_turn.defer_chat_turn" in named
    assert "tasks.app.worker_queues" in named
    assert "conversation.authz.get_owned_conversation" in named

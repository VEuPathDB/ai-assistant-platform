"""The suite runs on a foreign team's CI, so its imports are its contract.

Nothing of this deployment may resolve there: no ``pathfinder``, no
``assistant_core``. The walk below fails on the import statement and names the
module that added it, instead of failing later on a missing distribution.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

import mcp_conformance

SUITE = mcp_conformance.__name__

# Everything this deployment owns. A suite that reaches one of these cannot be
# run against a server we did not write.
FORBIDDEN_ROOTS = ("pathfinder", "assistant_core")

# The distributions the suite declares. An import outside this set is a
# dependency the runner was never told to install.
DECLARED = {"httpx", "mcp", "pydantic", "pytest"}


def _suite_modules() -> list[ModuleType]:
    return [
        mcp_conformance,
        *(
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(
                mcp_conformance.__path__,
                prefix=f"{SUITE}.",
            )
        ),
    ]


def _imported_names(module: ModuleType) -> set[str]:
    path = module.__file__
    assert path is not None
    names: set[str] = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _distributions(names: set[str]) -> set[str]:
    roots = {name.split(".")[0] for name in names}
    return {root for root in roots if root not in sys.stdlib_module_names} - {SUITE}


@pytest.mark.parametrize("module", _suite_modules(), ids=lambda m: m.__name__)
def test_no_suite_module_imports_this_deployment(module: ModuleType) -> None:
    reached = {
        name
        for name in _imported_names(module)
        if name.split(".")[0] in FORBIDDEN_ROOTS
    }

    assert reached == set()


@pytest.mark.parametrize("module", _suite_modules(), ids=lambda m: m.__name__)
def test_no_suite_module_imports_an_undeclared_distribution(
    module: ModuleType,
) -> None:
    reached = _distributions(_imported_names(module))

    assert reached <= DECLARED


def test_the_suite_ships_the_families_it_promises() -> None:
    shipped = {
        info.name.rsplit(".", 1)[-1]
        for info in pkgutil.walk_packages(mcp_conformance.__path__)
        if info.name.rsplit(".", 1)[-1].startswith("test_")
    }

    assert shipped == {
        "test_shape",
        "test_auth",
        "test_annotations",
        "test_errors",
        "test_timeouts",
        "test_stability",
    }

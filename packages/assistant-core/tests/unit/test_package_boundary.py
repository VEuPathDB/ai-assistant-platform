"""The boundary is an installation fact; this suite is the belt.

The package declares no dependency on ``pathfinder``, so a science import
cannot resolve. The walk below fails on the import statement instead of on
the missing distribution, and names the module that added it.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

import assistant_core

CORE = assistant_core.__name__

# The payloads the wire carries are model declarations, so they reach the
# model library and nothing else.
STREAM_PART_PAYLOAD_MODULES = {
    f"{CORE}.conversation.stream_parts.task_parts",
    f"{CORE}.conversation.stream_parts.turn_usage",
}
ALLOWED_STREAM_PART_PAYLOAD_IMPORTS = {"pydantic"}

# A tool source is declared and admitted as configuration, so these modules
# reach no agent framework and no MCP client.
MCP_CONFIG_MODULES = {
    f"{CORE}.mcp",
    f"{CORE}.mcp.admission",
    f"{CORE}.mcp.declaration",
}
ALLOWED_MCP_CONFIG_IMPORTS = {"pydantic"}

# The wrapper stack composes the agent framework's own toolsets and checks a
# payload against the schema its tool declared. It builds no MCP client.
MCP_WRAPPING_MODULES = {
    f"{CORE}.mcp.approval",
    f"{CORE}.mcp.untrusted",
    f"{CORE}.mcp.wrapping",
}
ALLOWED_MCP_WRAPPING_IMPORTS = {
    "jsonschema",
    "pydantic",
    "pydantic_ai",
    "pydantic_core",
}


def _core_modules() -> list[ModuleType]:
    return [
        assistant_core,
        *(
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(
                assistant_core.__path__,
                prefix=f"{CORE}.",
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


@pytest.mark.parametrize("module", _core_modules(), ids=lambda m: m.__name__)
def test_no_runtime_module_imports_the_science(module: ModuleType) -> None:
    reached = {
        name for name in _imported_names(module) if name.startswith("pathfinder")
    }

    assert reached == set()


def _distributions(names: set[str]) -> set[str]:
    roots = {name.split(".")[0] for name in names}
    return {root for root in roots if root not in sys.stdlib_module_names} - {CORE}


def test_the_declaration_and_admission_shapes_reach_only_pydantic() -> None:
    reached = {
        name
        for m in _core_modules()
        if m.__name__ in MCP_CONFIG_MODULES
        for name in _distributions(_imported_names(m))
    }

    assert reached == ALLOWED_MCP_CONFIG_IMPORTS


def test_the_wrapper_stack_reaches_the_framework_and_the_schema_check_only() -> None:
    reached = {
        name
        for m in _core_modules()
        if m.__name__ in MCP_WRAPPING_MODULES
        for name in _distributions(_imported_names(m))
    }

    assert reached == ALLOWED_MCP_WRAPPING_IMPORTS


def test_the_stream_part_payloads_reach_only_the_model_library() -> None:
    reached = {
        name
        for m in _core_modules()
        if m.__name__ in STREAM_PART_PAYLOAD_MODULES
        for name in _distributions(_imported_names(m))
    }

    assert reached == ALLOWED_STREAM_PART_PAYLOAD_IMPORTS


def test_no_runtime_module_imports_the_test_server() -> None:
    reached = {
        m.__name__
        for m in _core_modules()
        for name in _imported_names(m)
        if name == "fastmcp" or name.startswith("fastmcp.")
    }

    assert reached == set()

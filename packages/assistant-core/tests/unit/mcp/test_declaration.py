"""What an assistant declares, and what the declaration refuses."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from assistant_core.mcp.declaration import (
    ToolSourceDeclaration,
    ToolSourceDeclarations,
)
from assistant_core.spec import AssistantSpec


def _never_called(*args: object, **kwargs: object) -> object:
    msg = "a spec factory is not called in this suite"
    raise AssertionError(msg)


def _spec(**overrides: object) -> AssistantSpec:
    return AssistantSpec(
        assistant_id="declaring",
        build_graph=_never_called,
        build_initial_state=_never_called,
        build_turn_context=_never_called,
        build_mock_model=_never_called,
        **overrides,
    )


def test_a_declaration_asks_for_every_tool_and_is_optional_by_default() -> None:
    declaration = ToolSourceDeclaration(name="eda", source_id="veupathdb-eda")

    assert declaration.tools is None
    assert declaration.required is False
    assert declaration.always_approve == frozenset()


@pytest.mark.parametrize(
    "name",
    ["", "Eda", "1eda", "eda-1", "eda.one", "_eda", "e" * 33],
)
def test_the_local_name_must_be_a_lowercase_identifier(name: str) -> None:
    with pytest.raises(ValidationError):
        ToolSourceDeclaration(name=name, source_id="veupathdb-eda")


def test_a_declaration_names_a_source_it_cannot_leave_empty() -> None:
    with pytest.raises(ValidationError):
        ToolSourceDeclaration(name="eda", source_id="")


def test_a_declaration_is_frozen() -> None:
    declaration = ToolSourceDeclaration(name="eda", source_id="veupathdb-eda")

    with pytest.raises(ValidationError):
        declaration.required = True


def test_a_declaration_refuses_a_field_it_does_not_define() -> None:
    with pytest.raises(ValidationError):
        ToolSourceDeclaration(
            name="eda",
            source_id="veupathdb-eda",
            endpoint="https://elsewhere.example/mcp",
        )


def test_the_named_tools_become_frozen_sets() -> None:
    declaration = ToolSourceDeclaration(
        name="eda",
        source_id="veupathdb-eda",
        tools=["read_thing", "read_thing"],
        always_approve=["write_thing"],
    )

    assert declaration.tools == frozenset({"read_thing"})
    assert declaration.always_approve == frozenset({"write_thing"})


def test_two_declarations_cannot_claim_one_local_name() -> None:
    adapter = TypeAdapter(ToolSourceDeclarations)

    with pytest.raises(ValidationError):
        adapter.validate_python(
            [
                ToolSourceDeclaration(name="eda", source_id="veupathdb-eda"),
                ToolSourceDeclaration(name="eda", source_id="veupathdb-wdk"),
            ],
        )


def test_an_assistant_declares_no_tool_sources_by_default() -> None:
    assert _spec().tool_sources == ()


def test_the_spec_freezes_the_declarations_it_is_given() -> None:
    declaration = ToolSourceDeclaration(name="eda", source_id="veupathdb-eda")

    spec = _spec(tool_sources=[declaration])

    assert spec.tool_sources == (declaration,)
    with pytest.raises(ValidationError):
        spec.tool_sources = ()


def test_the_spec_refuses_two_sources_under_one_local_name() -> None:
    with pytest.raises(ValidationError):
        _spec(
            tool_sources=[
                ToolSourceDeclaration(name="eda", source_id="veupathdb-eda"),
                ToolSourceDeclaration(name="eda", source_id="veupathdb-wdk"),
            ],
        )

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from assistant_core.memory.schemas import MemoryEntryDraft, MemoryValue

DOMAIN_WORDS = ("falciparum", "organism", "gene", "kinome")


def _value(kind: str) -> MemoryValue:
    return MemoryValue(
        kind=kind,
        name="x",
        summary="y",
        tags=[],
        content={},
        created_at=datetime.now(UTC),
    )


def test_memory_value_round_trips() -> None:
    value = MemoryValue(
        kind="preference",
        name="preferred_units",
        summary="Counts are reported per thousand",
        tags=["units", "reporting"],
        site_id="site-a",
        content={"units": "per_thousand"},
        created_at=datetime.now(UTC),
    )
    dumped = value.model_dump(by_alias=True, mode="json")
    restored = MemoryValue.model_validate(dumped)
    assert restored == value
    assert restored.auto_retrieve is True


def test_a_kind_the_runtime_never_named_is_accepted() -> None:
    """The set of kinds is the host's, declared on its ``AssistantSpec``."""
    assert _value("dataset").kind == "dataset"


@pytest.mark.parametrize("kind", ["", "Gene Set", "gene-set", "2nd", "gene set"])
def test_a_kind_that_is_not_a_snake_case_name_is_refused(kind: str) -> None:
    with pytest.raises(ValidationError, match="snake_case"):
        _value(kind)


def test_the_draft_field_descriptions_name_no_domain() -> None:
    """The schema the model reads is coaching, so it carries no host's science."""
    described = " ".join(
        str(field["description"])
        for field in MemoryEntryDraft.model_json_schema()["properties"].values()
    ).lower()

    for word in DOMAIN_WORDS:
        assert word not in described

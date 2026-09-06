from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from assistant_core.memory.schemas import MemoryKind, MemoryValue


def test_memory_value_round_trips() -> None:
    value = MemoryValue(
        kind="gene_set",
        name="drug_targets_malaria",
        summary="Validated phase-2 drug targets in P. falciparum",
        tags=["plasmodb", "phase2"],
        site_id="plasmodb",
        content={"gene_ids": ["PF3D7_0102500"], "source": "geneset:abc"},
        created_at=datetime.now(UTC),
    )
    dumped = value.model_dump(by_alias=True, mode="json")
    restored = MemoryValue.model_validate(dumped)
    assert restored == value
    assert restored.auto_retrieve is True


def test_memory_value_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        MemoryValue(
            kind="bogus",
            name="x",
            summary="y",
            tags=[],
            content={},
            created_at=datetime.now(UTC),
        )


def test_all_memory_kinds_accepted() -> None:
    kinds: list[MemoryKind] = [
        "gene_set",
        "strategy",
        "preference",
        "knowledge",
        "case",
    ]
    for k in kinds:
        MemoryValue(
            kind=k,
            name="x",
            summary="y",
            tags=[],
            content={},
            created_at=datetime.now(UTC),
        )

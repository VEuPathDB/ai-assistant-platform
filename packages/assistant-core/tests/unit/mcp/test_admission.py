"""Which servers a deployment admits, and where that set comes from."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from pydantic import ValidationError

from assistant_core.mcp.admission import (
    AdmissionRecord,
    AdmittedSources,
    get_admitted_sources,
    install_admitted_sources,
)
from assistant_core.platform.config import RuntimeSettings

EDA = AdmissionRecord(
    source_id="veupathdb-eda",
    endpoint="https://eda.example/mcp",
    part_namespace="eda",
)


@pytest.fixture(autouse=True)
def _restore_admitted_sources() -> Generator[None]:
    yield
    install_admitted_sources(AdmittedSources())


def test_an_admitted_record_carries_no_credential_and_asks_by_annotation() -> None:
    assert EDA.credential_mode == "none"
    assert EDA.approval_policy == "annotations"
    assert EDA.max_call_seconds == 60
    assert EDA.content_trust == "untrusted"


def test_a_record_is_frozen() -> None:
    with pytest.raises(ValidationError):
        EDA.endpoint = "https://elsewhere.example/mcp"


def test_a_record_refuses_a_field_it_does_not_define() -> None:
    with pytest.raises(ValidationError):
        AdmissionRecord(
            source_id="veupathdb-eda",
            endpoint="https://eda.example/mcp",
            part_namespace="eda",
            authorization="Bearer secret",
        )


@pytest.mark.parametrize(
    "namespace",
    ["", "Eda", "1eda", "eda_one", "eda.one", "-eda", "eda "],
)
def test_the_part_namespace_grammar_is_enforced(namespace: str) -> None:
    with pytest.raises(ValidationError):
        AdmissionRecord(
            source_id="veupathdb-eda",
            endpoint="https://eda.example/mcp",
            part_namespace=namespace,
        )


def test_a_part_namespace_may_carry_hyphens() -> None:
    record = AdmissionRecord(
        source_id="veupathdb-eda",
        endpoint="https://eda.example/mcp",
        part_namespace="veupathdb-eda",
    )

    assert record.part_namespace == "veupathdb-eda"


def test_content_trust_cannot_be_anything_but_untrusted() -> None:
    with pytest.raises(ValidationError):
        AdmissionRecord(
            source_id="veupathdb-eda",
            endpoint="https://eda.example/mcp",
            part_namespace="eda",
            content_trust="trusted",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("credential_mode", "pathfinder_service"),
        ("approval_policy", "never"),
        ("max_call_seconds", 0),
        ("endpoint", ""),
        ("source_id", ""),
    ],
)
def test_a_record_refuses_a_value_outside_its_domain(
    field: str,
    value: object,
) -> None:
    fields = {
        "source_id": "veupathdb-eda",
        "endpoint": "https://eda.example/mcp",
        "part_namespace": "eda",
        field: value,
    }

    with pytest.raises(ValidationError):
        AdmissionRecord(**fields)


def test_one_source_id_is_admitted_once() -> None:
    with pytest.raises(ValidationError):
        AdmittedSources(
            records=(
                EDA,
                AdmissionRecord(
                    source_id="veupathdb-eda",
                    endpoint="https://other.example/mcp",
                    part_namespace="other",
                ),
            ),
        )


def test_an_unadmitted_source_resolves_to_nothing() -> None:
    admitted = AdmittedSources(records=(EDA,))

    assert admitted.resolve("veupathdb-wdk") is None


def test_resolve_returns_the_record_the_operator_admitted() -> None:
    admitted = AdmittedSources(records=(EDA,))

    assert admitted.resolve("veupathdb-eda") == EDA


def test_a_process_admits_nothing_until_the_host_installs_a_set() -> None:
    assert get_admitted_sources().records == ()


def test_installing_replaces_the_admitted_set() -> None:
    install_admitted_sources(AdmittedSources(records=(EDA,)))

    assert get_admitted_sources().resolve("veupathdb-eda") == EDA


def test_the_admitted_set_is_never_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PART_NAMESPACE", "eda")
    monkeypatch.setenv("ENDPOINT", "https://elsewhere.example/mcp")
    monkeypatch.setenv("CREDENTIAL_MODE", "veupathdb_user")
    monkeypatch.setenv("RECORDS", "[]")

    read = set(RuntimeSettings().model_dump())

    assert read.isdisjoint(
        set(AdmissionRecord.model_fields) | set(AdmittedSources.model_fields),
    )
    assert get_admitted_sources().records == ()

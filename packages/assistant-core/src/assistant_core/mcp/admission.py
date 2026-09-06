"""Which servers a deployment admits, and where the runtime reads that set."""

from collections import Counter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type CredentialMode = Literal["none", "service", "veupathdb_user"]
type ApprovalPolicy = Literal["annotations", "always"]


class AdmissionRecord(BaseModel):
    """One admitted server. Operator configuration, never request data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    credential_mode: CredentialMode = "none"
    part_namespace: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    approval_policy: ApprovalPolicy = "annotations"
    max_call_seconds: int = Field(default=60, ge=1)
    content_trust: Literal["untrusted"] = "untrusted"


class AdmittedSources(BaseModel):
    """Every server this deployment admits, by source id."""

    model_config = ConfigDict(frozen=True)

    records: tuple[AdmissionRecord, ...] = ()

    @model_validator(mode="after")
    def _refuse_repeated_source_ids(self) -> Self:
        counted = Counter(record.source_id for record in self.records)
        repeated = sorted(name for name, count in counted.items() if count > 1)
        if repeated:
            msg = f"a source id is admitted once: {', '.join(repeated)}"
            raise ValueError(msg)
        return self

    def resolve(self, source_id: str) -> AdmissionRecord | None:
        """The record admitting this id, or None when nothing admits it."""
        return next(
            (record for record in self.records if record.source_id == source_id),
            None,
        )


class _AdmittedSourcesSource:
    """The admitted set in force. The host installs it, at start."""

    def __init__(self) -> None:
        self._admitted = AdmittedSources()

    def use(self, admitted: AdmittedSources) -> None:
        self._admitted = admitted

    def read(self) -> AdmittedSources:
        return self._admitted


_source = _AdmittedSourcesSource()


def install_admitted_sources(admitted: AdmittedSources) -> None:
    """Admit these servers for this process."""
    _source.use(admitted)


def get_admitted_sources() -> AdmittedSources:
    """The servers this process admits."""
    return _source.read()


__all__ = [
    "AdmissionRecord",
    "AdmittedSources",
    "ApprovalPolicy",
    "CredentialMode",
    "get_admitted_sources",
    "install_admitted_sources",
]

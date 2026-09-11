"""Which servers a deployment admits, and where the runtime reads that set."""

import re
from collections import Counter
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

# The one credential mode the runtime interprets: a source admitted on it is
# never asked for a credential. Every other mode is the deployment's own word
# and reaches the host's credential callback unread.
NO_CREDENTIAL = "none"

# The shape of a mode, which the runtime owns. Which modes exist is the
# deployment's.
_CREDENTIAL_MODE_SHAPE = re.compile(r"[a-z][a-z0-9_]*")

type ApprovalPolicy = Literal["annotations", "always"]


class AdmissionRecord(BaseModel):
    """One admitted server. Operator configuration, never request data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    credential_mode: str = NO_CREDENTIAL
    part_namespace: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    approval_policy: ApprovalPolicy = "annotations"
    max_call_seconds: int = Field(default=60, ge=1)
    content_trust: Literal["untrusted"] = "untrusted"

    @field_validator("credential_mode")
    @classmethod
    def _mode_is_a_name(cls, value: str) -> str:
        if _CREDENTIAL_MODE_SHAPE.fullmatch(value) is None:
            msg = "a credential mode is a non-empty snake_case name"
            raise ValueError(msg)
        return value


class AdmittedSources(BaseModel):
    """Every server this deployment admits, by source id."""

    model_config = ConfigDict(frozen=True)

    records: tuple[AdmissionRecord, ...] = ()

    # The host installs one set for the process, so what it does not admit is
    # a fact a reader needs once.
    _named_absent: set[str] = PrivateAttr(default_factory=set)

    @model_validator(mode="after")
    def _refuse_repeated_source_ids(self) -> Self:
        counted = Counter(record.source_id for record in self.records)
        repeated = sorted(name for name, count in counted.items() if count > 1)
        if repeated:
            msg = f"a source id is admitted once: {', '.join(repeated)}"
            raise ValueError(msg)
        return self

    def note_absent(self, source_id: str) -> bool:
        """True the first time this set is asked for a source it does not admit."""
        if source_id in self._named_absent:
            return False
        self._named_absent.add(source_id)
        return True

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
    "NO_CREDENTIAL",
    "AdmissionRecord",
    "AdmittedSources",
    "ApprovalPolicy",
    "get_admitted_sources",
    "install_admitted_sources",
]

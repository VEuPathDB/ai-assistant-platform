"""Registry of the ``data-*`` stream parts the generated schema must expose."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, create_model

from assistant_core.platform.pydantic_base import CamelModel

_KIND_PREFIX = "data-"

_INDEX_DOC = (
    "Index of stream-part payload schemas. Never called - exists for "
    "OpenAPI generation."
)


class DuplicateStreamPartError(ValueError):
    """Two registrations claim the same schema entry."""

    def __init__(self, name: str) -> None:
        super().__init__(f"stream part already registered: {name}")
        self.name = name


class InvalidStreamPartNameError(ValueError):
    """A kind or schema name does not map to a Python identifier."""

    def __init__(self, name: str) -> None:
        super().__init__(f"stream part name is not a data-<identifier>: {name}")
        self.name = name


def _schema_name(kind: str) -> str:
    if not kind.startswith(_KIND_PREFIX):
        raise InvalidStreamPartNameError(kind)
    name = kind.removeprefix(_KIND_PREFIX).replace("-", "_").replace(".", "_")
    if not name.isidentifier():
        raise InvalidStreamPartNameError(kind)
    return name


@dataclass(frozen=True, slots=True)
class StreamPartEntry:
    """A payload model, and the part kind that carries it when one does."""

    schema_name: str
    model: type[BaseModel]
    kind: str | None


class StreamPartRegistry:
    """Collects the payload models of every registered stream part.

    Core registers the runtime parts; each product registers its own. The
    registry is the only list the OpenAPI schema index reads.
    """

    def __init__(self) -> None:
        self._entries: dict[str, StreamPartEntry] = {}

    def register(self, kind: str, model: type[BaseModel]) -> None:
        """Register the payload model of an emitted ``data-*`` part."""
        entry = StreamPartEntry(schema_name=_schema_name(kind), model=model, kind=kind)
        self._add(entry)

    def register_schema_only(self, schema_name: str, model: type[BaseModel]) -> None:
        """Expose a payload model that no emitted part kind carries."""
        if not schema_name.isidentifier():
            raise InvalidStreamPartNameError(schema_name)
        self._add(StreamPartEntry(schema_name=schema_name, model=model, kind=None))

    def entries(self) -> tuple[StreamPartEntry, ...]:
        """Entries ordered by schema name, so the spec does not track import order."""
        return tuple(self._entries[name] for name in sorted(self._entries))

    def kinds(self) -> frozenset[str]:
        """Every registered part kind, without the schema-only entries."""
        return frozenset(
            entry.kind for entry in self._entries.values() if entry.kind is not None
        )

    def schema_index_model(self) -> type[CamelModel]:
        """Build the model whose fields give the generator a $ref per entry."""
        fields: dict[str, Any] = {
            entry.schema_name: (entry.model | None, None) for entry in self.entries()
        }
        return create_model(
            "StreamPartsSchemaIndex",
            __base__=CamelModel,
            __doc__=_INDEX_DOC,
            **fields,
        )

    def _add(self, entry: StreamPartEntry) -> None:
        if entry.schema_name in self._entries:
            raise DuplicateStreamPartError(entry.kind or entry.schema_name)
        self._entries[entry.schema_name] = entry

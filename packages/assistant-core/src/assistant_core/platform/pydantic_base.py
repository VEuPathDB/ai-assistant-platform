"""Shared Pydantic base model and annotated float types for JSON serialization.

All domain/service types that need camelCase JSON output inherit from
:class:`CamelModel`. The float aliases below set the rounding applied during
serialization.
"""

from collections.abc import Callable
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, PlainSerializer, computed_field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model with camelCase JSON aliases. snake_case kwargs only in Python.

    Do NOT set per-field ``Field(alias=...)`` on CamelModel subclasses — the
    class-level ``alias_generator`` covers it and keeps pyright happy. Explicit
    ``alias=`` forces pyright to require camelCase kwargs, breaking the invariant.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Computed[T](Protocol):
    """A class attribute a type checker reads as the value it computes."""

    def __get__(self, instance: object, owner: type | None = None, /) -> T: ...


def computed[S, T](func: Callable[[S], T]) -> Computed[T]:
    """A computed field, serialized like a field and typed as its value.

    A ``@computed_field`` stacked on ``@property`` is a decorated property, which
    mypy refuses; this wraps the property itself, so both checkers read ``T``.
    """
    return computed_field(property(func))


RoundedFloat = Annotated[
    float, PlainSerializer(lambda v: round(v, 4), return_type=float)
]
"""Float rounded to 4 decimal places during serialization."""

RoundedFloat2 = Annotated[
    float, PlainSerializer(lambda v: round(v, 2), return_type=float)
]
"""Float rounded to 2 decimal places during serialization."""

"""Shared Pydantic base model and annotated float types for JSON serialization.

All domain/service types that need camelCase JSON output inherit from
:class:`CamelModel`. The float aliases below set the rounding applied during
serialization.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model with camelCase JSON aliases. snake_case kwargs only in Python.

    Do NOT set per-field ``Field(alias=...)`` on CamelModel subclasses — the
    class-level ``alias_generator`` covers it and keeps pyright happy. Explicit
    ``alias=`` forces pyright to require camelCase kwargs, breaking the invariant.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


RoundedFloat = Annotated[
    float, PlainSerializer(lambda v: round(v, 4), return_type=float)
]
"""Float rounded to 4 decimal places during serialization."""

RoundedFloat2 = Annotated[
    float, PlainSerializer(lambda v: round(v, 2), return_type=float)
]
"""Float rounded to 2 decimal places during serialization."""

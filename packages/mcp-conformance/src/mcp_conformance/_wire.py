"""The base every model here shares: camelCase on the wire, snake_case in code."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


class WireModel(BaseModel):
    """Reads a server's JSON, writes the report's JSON, and never mutates."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        coerce_numbers_to_str=True,
    )

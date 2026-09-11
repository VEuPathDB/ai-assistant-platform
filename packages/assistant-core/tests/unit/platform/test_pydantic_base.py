"""A computed field serializes like a field and is typed as its value."""

from typing import assert_type

from assistant_core.platform.pydantic_base import CamelModel, computed


class _Box(CamelModel):
    inner_size: int

    @computed
    def outer_size(self) -> int:
        return self.inner_size + 2


def test_a_computed_field_is_read_as_its_value() -> None:
    box = _Box(inner_size=3)

    assert_type(box.outer_size, int)
    assert box.outer_size == 5


def test_a_computed_field_serializes_under_its_camel_alias() -> None:
    assert _Box(inner_size=3).model_dump(by_alias=True) == {
        "innerSize": 3,
        "outerSize": 5,
    }
    assert "outerSize" in _Box.model_json_schema(mode="serialization")["properties"]

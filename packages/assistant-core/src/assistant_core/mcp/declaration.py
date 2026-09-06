"""What an assistant asks for. The runtime resolves every declaration."""

from collections import Counter
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class ToolSourceDeclaration(BaseModel):
    """One MCP server this assistant asks for. The runtime resolves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=32)
    source_id: str = Field(min_length=1)
    tools: frozenset[str] | None = None
    required: bool = False
    always_approve: frozenset[str] = frozenset()


def _refuse_repeated_names(
    declarations: tuple[ToolSourceDeclaration, ...],
) -> tuple[ToolSourceDeclaration, ...]:
    counted = Counter(declaration.name for declaration in declarations)
    repeated = sorted(name for name, count in counted.items() if count > 1)
    if repeated:
        msg = f"a tool source name is declared once: {', '.join(repeated)}"
        raise ValueError(msg)
    return declarations


# The name is also the tool-name prefix, so two sources cannot share one.
type ToolSourceDeclarations = Annotated[
    tuple[ToolSourceDeclaration, ...],
    AfterValidator(_refuse_repeated_names),
]


__all__ = ["ToolSourceDeclaration", "ToolSourceDeclarations"]

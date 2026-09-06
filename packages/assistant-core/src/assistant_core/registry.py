"""The assistants installed in one deployment.

Composition builds the registry; the runtime resolves a turn's assistant
through it and never names one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from assistant_core.spec import AssistantSpec


class DuplicateAssistantError(ValueError):
    """Two specs claim one assistant id."""

    def __init__(self, assistant_id: str) -> None:
        super().__init__(f"assistant already registered: {assistant_id}")
        self.assistant_id = assistant_id


class UnknownDefaultAssistantError(ValueError):
    """The default names an assistant the registry does not hold."""

    def __init__(self, assistant_id: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"default assistant {assistant_id!r} is not registered: {known}",
        )
        self.assistant_id = assistant_id
        self.known = known


class UnknownAssistantError(LookupError):
    """A request names an assistant this deployment does not serve.

    The transport boundary answers it as a 404.
    """

    def __init__(self, assistant_id: str, known: tuple[str, ...]) -> None:
        super().__init__(f"unknown assistant: {assistant_id}")
        self.assistant_id = assistant_id
        self.known = known


class AssistantRegistry:
    """Every assistant this deployment serves, and which one is the default."""

    def __init__(
        self,
        *,
        specs: Iterable[AssistantSpec],
        default_id: str,
    ) -> None:
        by_id: dict[str, AssistantSpec] = {}
        for spec in specs:
            if spec.assistant_id in by_id:
                raise DuplicateAssistantError(spec.assistant_id)
            by_id[spec.assistant_id] = spec
        if default_id not in by_id:
            raise UnknownDefaultAssistantError(default_id, tuple(by_id))
        self._by_id: Mapping[str, AssistantSpec] = by_id
        self.default_id = default_id

    def resolve(self, assistant_id: str) -> AssistantSpec:
        spec = self._by_id.get(assistant_id)
        if spec is None:
            raise UnknownAssistantError(assistant_id, self.ids())
        return spec

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def specs(self) -> tuple[AssistantSpec, ...]:
        return tuple(self._by_id.values())

    def checkpoint_types(self) -> tuple[type, ...]:
        """Every state type any installed assistant checkpoints.

        One checkpoint table serves every assistant, so the msgpack allowlist
        is the union.
        """
        seen: dict[type, None] = {}
        for spec in self._by_id.values():
            seen.update(dict.fromkeys(spec.checkpoint_types))
        return tuple(seen)


__all__ = [
    "AssistantRegistry",
    "DuplicateAssistantError",
    "UnknownAssistantError",
    "UnknownDefaultAssistantError",
]

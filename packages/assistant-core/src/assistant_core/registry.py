"""The assistants installed in one deployment, and which one answers a turn.

Composition builds the registry; the runtime resolves a turn's assistant
through it and never names one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from assistant_core.conversation.authz import conversation_assistant_id
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


class AssistantMismatchError(ValueError):
    """A request names an assistant other than the one its thread was created with.

    The transport boundary answers it as a 409.
    """

    def __init__(self, requested: str, existing: str) -> None:
        super().__init__(
            f"conversation belongs to assistant {existing!r}, not {requested!r}",
        )
        self.requested = requested
        self.existing = existing


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


def assistant_for_turn(
    *,
    registry: AssistantRegistry,
    existing_id: str | None,
    requested_id: str | None,
) -> AssistantSpec:
    """The assistant a turn runs under.

    A thread that does not exist yet takes the requested assistant, or the
    default. An existing thread keeps the assistant it was created with, and a
    request that names another one is refused.
    """
    if existing_id is None:
        return registry.resolve(requested_id or registry.default_id)
    if requested_id is not None and requested_id != existing_id:
        raise AssistantMismatchError(requested_id, existing_id)
    return registry.resolve(existing_id)


async def resolve_turn_assistant(
    *,
    registry: AssistantRegistry,
    conversation_id: UUID | None,
    requested_id: str | None,
) -> AssistantSpec:
    """The assistant this turn runs under, reading the thread's own row.

    A caller that is about to create the thread passes no id and reads no row.
    """
    existing = (
        None
        if conversation_id is None
        else await conversation_assistant_id(conversation_id)
    )
    return assistant_for_turn(
        registry=registry,
        existing_id=existing,
        requested_id=requested_id,
    )


class RegistryNotInstalledError(RuntimeError):
    """Work outside a request asked for the assistants before a host installed them."""

    def __init__(self) -> None:
        super().__init__(
            "no assistant registry is installed: call "
            "install_assistant_registry(registry) during composition",
        )


class _InstalledRegistry:
    """The assistants this process serves."""

    def __init__(self) -> None:
        self._registry: AssistantRegistry | None = None

    def install(self, registry: AssistantRegistry) -> None:
        self._registry = registry

    def reset(self) -> None:
        self._registry = None

    def read(self) -> AssistantRegistry:
        if self._registry is None:
            raise RegistryNotInstalledError
        return self._registry


_installed = _InstalledRegistry()


def install_assistant_registry(registry: AssistantRegistry) -> None:
    """Serve this deployment's assistants to work that carries no request."""
    _installed.install(registry)


def reset_assistant_registry() -> None:
    """Serve no assistants again, as a process that installed none does."""
    _installed.reset()


def assistant_registry() -> AssistantRegistry:
    """The installed registry."""
    return _installed.read()


__all__ = [
    "AssistantMismatchError",
    "AssistantRegistry",
    "DuplicateAssistantError",
    "RegistryNotInstalledError",
    "UnknownAssistantError",
    "UnknownDefaultAssistantError",
    "assistant_for_turn",
    "assistant_registry",
    "install_assistant_registry",
    "reset_assistant_registry",
    "resolve_turn_assistant",
]

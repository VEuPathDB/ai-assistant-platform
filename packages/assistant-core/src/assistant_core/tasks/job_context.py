"""State a deferring process holds that a worker cannot re-derive.

A worker inherits no context variable from the process that deferred the job,
so the host captures what its tools need at the call and restores it around
the body. The runtime names none of it.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, nullcontext
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, PlainSerializer, SecretStr


def _reveal(secret: SecretStr) -> str:
    return secret.get_secret_value()


# A credential that masks itself in a repr and still crosses the queue.
CarriedSecret = Annotated[SecretStr, PlainSerializer(_reveal, return_type=str)]


class DurableJobState(BaseModel):
    """What one durable call carries from the deferring process to the worker.

    A host subclasses this and types every credential ``CarriedSecret``, so the
    state masks itself wherever it is printed and the worker reads the value
    back with ``get_secret_value()`` at the point of use.
    """

    model_config = ConfigDict(extra="ignore")


class DurableJobContext(Protocol):
    """What a host carries from a durable call to the worker that answers it."""

    @property
    def state_type(self) -> type[DurableJobState]: ...

    def capture(self) -> DurableJobState: ...

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]: ...


class NoJobContext:
    """The default: the worker re-derives everything the body needs."""

    state_type = DurableJobState

    def capture(self) -> DurableJobState:
        return DurableJobState()

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        del state
        return nullcontext()


class _InstalledJobContext:
    """The job context this process runs durable work under."""

    def __init__(self) -> None:
        self._context: DurableJobContext = NoJobContext()

    def install(self, context: DurableJobContext) -> None:
        self._context = context

    def reset(self) -> None:
        self._context = NoJobContext()

    def read(self) -> DurableJobContext:
        return self._context


_installed = _InstalledJobContext()


def install_durable_job_context(context: DurableJobContext) -> None:
    """Carry this host's per-call state into every durable job."""
    _installed.install(context)


def reset_durable_job_context() -> None:
    """Carry nothing again, as a process that installed no context does."""
    _installed.reset()


def durable_job_context() -> DurableJobContext:
    """The job context in force for this process."""
    return _installed.read()


__all__ = [
    "CarriedSecret",
    "DurableJobContext",
    "DurableJobState",
    "NoJobContext",
    "durable_job_context",
    "install_durable_job_context",
    "reset_durable_job_context",
]

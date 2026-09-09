"""Context variables for request-scoped data."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistant_core.platform.types import ReasoningEffort

# The application a call acts as when it names none. The value is also the
# stored default of every application_id column.
DEFAULT_APPLICATION_ID = "default"

# Request ID for tracing
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Current user ID
user_id_ctx: ContextVar[UUID | None] = ContextVar("user_id", default=None)

# Application the request is made on behalf of
application_id_ctx: ContextVar[str] = ContextVar(
    "application_id", default=DEFAULT_APPLICATION_ID
)


def calling_application() -> str:
    """The application the current request or worker job acts as."""
    return application_id_ctx.get()


# Current site context
site_id_ctx: ContextVar[str | None] = ContextVar("site_id", default=None)

# Conversation stream identity (set by the chat orchestrator).
stream_id_ctx: ContextVar[str | None] = ContextVar("stream_id", default=None)

# Active operation identity (set by the chat orchestrator).
operation_id_ctx: ContextVar[str | None] = ContextVar("operation_id", default=None)


class PhaseOverrides(BaseModel):
    """The per-role model and reasoning picks one request carries.

    The roles and the model ids are validated on the request body; this is the
    validated pair, as the work a turn starts can read it.
    """

    model_config = ConfigDict(frozen=True)

    models: dict[str, str] = Field(default_factory=dict)
    reasoning: dict[str, ReasoningEffort] = Field(default_factory=dict)


_NO_OVERRIDES = PhaseOverrides()

# This turn's picks, for work that outlives the turn that started it.
phase_overrides_ctx: ContextVar[PhaseOverrides] = ContextVar(
    "phase_overrides", default=_NO_OVERRIDES
)


@contextmanager
def attach_phase_overrides(overrides: PhaseOverrides) -> Iterator[None]:
    """Run a turn under its own picks."""
    token = phase_overrides_ctx.set(overrides)
    try:
        yield
    finally:
        phase_overrides_ctx.reset(token)

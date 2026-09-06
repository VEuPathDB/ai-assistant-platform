"""Context variables for request-scoped data."""

from contextvars import ContextVar
from uuid import UUID

# The application a call acts as when it names none. The value is also the
# stored default of every application_id column.
DEFAULT_APPLICATION_ID = "pathfinder"

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

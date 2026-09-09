"""The context variables a job body runs under.

A worker inherits no ``ContextVar`` from the process that deferred the job, so
these helpers set the values for the block and reset them on exit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from assistant_core.conversation.authz import conversation_application_id
from assistant_core.platform.context import application_id_ctx, user_id_ctx


@asynccontextmanager
async def attach_user_id(user_id: UUID | None) -> AsyncIterator[None]:
    """Run the block as ``user_id``."""
    reset = user_id_ctx.set(user_id)
    try:
        yield
    finally:
        user_id_ctx.reset(reset)


@asynccontextmanager
async def attach_conversation_application(
    conversation_id: UUID,
) -> AsyncIterator[None]:
    """Run the block as the application that holds ``conversation_id``.

    The thread row is the only record of which application a turn belongs to,
    so a job that cannot read it must not run.
    """
    application_id = await conversation_application_id(conversation_id)
    if application_id is None:
        msg = f"conversation {conversation_id} not found"
        raise LookupError(msg)
    reset = application_id_ctx.set(application_id)
    try:
        yield
    finally:
        application_id_ctx.reset(reset)


__all__ = ["attach_conversation_application", "attach_user_id"]

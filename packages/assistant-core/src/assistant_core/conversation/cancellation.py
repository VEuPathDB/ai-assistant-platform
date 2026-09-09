"""Turn cancellation for a thread.

Stop writes a request row that the worker running the turn polls. A worker
that has been silent longer than the host's heartbeat window reads nothing, so
the host also releases the turn through the callable it supplies.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.conversation.authz import get_visible_conversation
from assistant_core.errors import TurnStillRunningError
from assistant_core.persistence.models import ConversationEvent
from assistant_core.persistence.repositories.chat_turn_cancellations import (
    ChatTurnCancellationRepository,
)
from assistant_core.persistence.repositories.conversation import ConversationRepository
from assistant_core.platform.db import async_session_factory

STOP_POLL_INTERVAL_SECONDS = 0.05
STOP_WAIT_TIMEOUT_SECONDS = 30.0

# What the host runs to end a turn whose worker is already gone. The runtime
# owns no job queue, so releasing the job is the host's half of a stop.
ReleaseDeadTurn = Callable[[UUID], Awaitable[None]]


async def _open_turns(conversation_ids: Sequence[UUID]) -> dict[UUID, UUID]:
    """The turn each of these threads is still writing, keyed by thread.

    A thread whose newest chunk closes the stream is left out.
    """
    if not conversation_ids:
        return {}
    newest = (
        select(ConversationEvent)
        .where(
            ConversationEvent.conversation_id.in_(conversation_ids),
            ConversationEvent.task_id.is_(None),
        )
        .distinct(ConversationEvent.conversation_id)
        .order_by(ConversationEvent.conversation_id, ConversationEvent.id.desc())
    )
    async with async_session_factory() as session:
        rows = (await session.scalars(newest)).all()
    return {
        row.conversation_id: row.turn_id
        for row in rows
        if row.turn_id is not None and row.chunk.get("type") != "done"
    }


async def cancel_in_flight_turn(conversation_id: UUID) -> bool:
    """Ask the worker running the thread's newest turn to stop.

    Reports whether a turn was still in flight to cancel.
    """
    open_turns = await _open_turns([conversation_id])
    if conversation_id not in open_turns:
        return False
    repo = ChatTurnCancellationRepository(session_factory=async_session_factory)
    await repo.request_cancel(
        conversation_id=conversation_id,
        turn_id=open_turns[conversation_id],
    )
    return True


async def stop_turns_and_wait(
    conversation_ids: Sequence[UUID],
    *,
    release_dead_turn: ReleaseDeadTurn,
    timeout_seconds: float = STOP_WAIT_TIMEOUT_SECONDS,
) -> list[UUID]:
    """Stop every in-flight turn on these threads and wait for their workers.

    A worker appends to a thread until it reads the stop, so a caller that
    removes the thread waits for the closing chunk first. Reports the threads
    whose worker did not close its turn inside the window.
    """
    repo = ChatTurnCancellationRepository(session_factory=async_session_factory)
    open_turns = await _open_turns(conversation_ids)
    for conversation_id, turn_id in open_turns.items():
        await repo.request_cancel(conversation_id=conversation_id, turn_id=turn_id)
        await release_dead_turn(conversation_id)
    pending = list(open_turns)
    deadline = time.monotonic() + timeout_seconds
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(STOP_POLL_INTERVAL_SECONDS)
        pending = list(await _open_turns(pending))
    return pending


async def stop_turn_before_delete(
    conversation_id: UUID,
    *,
    release_dead_turn: ReleaseDeadTurn,
    timeout_seconds: float = STOP_WAIT_TIMEOUT_SECONDS,
) -> None:
    """Stop the thread's turn and wait for the worker before the row goes.

    A worker appends to a thread until it reads the stop; removing the row
    under it breaks every write that follows.
    """
    still_running = await stop_turns_and_wait(
        [conversation_id],
        release_dead_turn=release_dead_turn,
        timeout_seconds=timeout_seconds,
    )
    if still_running:
        raise TurnStillRunningError(conversation_id)


async def turn_is_cancelled(*, conversation_id: UUID, turn_id: UUID) -> bool:
    """Whether a stop has been requested for one turn."""
    repo = ChatTurnCancellationRepository(session_factory=async_session_factory)
    return await repo.is_cancelled(conversation_id=conversation_id, turn_id=turn_id)


async def cancel_active_turn(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    release_dead_turn: ReleaseDeadTurn,
) -> None:
    """Stop the caller's own thread, and release the job if its worker is gone."""
    await get_visible_conversation(
        ConversationRepository(session),
        conversation_id,
        user_id,
    )
    if await cancel_in_flight_turn(conversation_id):
        await release_dead_turn(conversation_id)

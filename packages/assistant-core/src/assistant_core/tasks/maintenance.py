"""Release the lock and close the stream a killed worker leaves behind."""

from __future__ import annotations

import warnings
from uuid import UUID

from procrastinate.jobs import Job, Status
from pydantic import ValidationError
from pydantic_ai.ui.vercel_ai.response_types import (
    DoneChunk,
    ErrorChunk,
    FinishChunk,
)
from sqlalchemy import select

from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.conversation.open_tool_calls import close_open_tool_calls
from assistant_core.graph.stream_events import turn_failed_event
from assistant_core.persistence.models import ConversationEvent
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import get_logger
from assistant_core.tasks.app import task_app
from assistant_core.tasks.chat_turn import ChatTurnJobArgs
from assistant_core.tasks.names import CHAT_TURN_TASK

logger = get_logger(__name__)

_STALLED_TURN_ERROR = (
    "The worker running this turn stopped before it finished. "
    "Send the message again to retry."
)

_DEAD_WORKER_ERROR = (
    "The worker running this turn stopped, which an out-of-memory kill can "
    "cause. Send the message again to retry."
)


async def _dead_workers_jobs() -> list[Job]:
    """The jobs held by a worker whose heartbeat stopped."""
    window = get_runtime_settings().worker_dead_heartbeat_seconds
    return list(
        await task_app().job_manager.get_stalled_jobs(
            seconds_since_heartbeat=window,
        ),
    )


async def _long_running_jobs() -> list[Job]:
    """The jobs in ``doing`` past the age timeout, whatever their worker says."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return list(
            await task_app().job_manager.get_stalled_jobs(
                nb_seconds=get_runtime_settings().worker_stalled_job_timeout_seconds,
            ),
        )


async def release_stalled_jobs() -> None:
    """Fail every job no live worker holds, without retrying it.

    A dead worker is named by its heartbeat, so a killed process releases its
    lock one to two minutes later. The started-age timeout stays as the
    backstop for a job that runs too long on a worker that still answers.
    """
    reasons: dict[int | None, tuple[Job, str]] = {
        job.id: (job, _STALLED_TURN_ERROR) for job in await _long_running_jobs()
    }
    reasons.update(
        {job.id: (job, _DEAD_WORKER_ERROR) for job in await _dead_workers_jobs()},
    )
    for job, error_text in reasons.values():
        await release_job(job, error_text)


async def release_dead_turn(conversation_id: UUID) -> None:
    """Fail the thread's chat turn when the worker holding it is gone.

    A stop reaches a live worker over the database; a worker silent past the
    dead-heartbeat window reads nothing, so the turn ends here instead. A
    worker that died inside that window still owns its turn.
    """
    for job in await _dead_workers_jobs():
        if job.task_name == CHAT_TURN_TASK and job.lock == str(conversation_id):
            await release_job(job, _DEAD_WORKER_ERROR)


async def release_job(job: Job, error_text: str) -> None:
    """End the job's stream, then fail the job so its lock releases."""
    # The terminator is written first: the thread lock is still held, so no
    # successor turn can interleave its chunks with it.
    await _close_stalled_turn(job, error_text)
    await task_app().job_manager.finish_job(
        job,
        status=Status.FAILED,
        delete_job=False,
    )
    logger.warning(
        "Released a stalled job",
        job_id=job.id,
        task_name=job.task_name,
        queue_name=job.queue,
        lock=job.lock,
        error_text=error_text,
    )


async def _close_stalled_turn(job: Job, error_text: str) -> None:
    """End the stream a killed turn left open, so subscribers stop waiting."""
    if job.task_name != CHAT_TURN_TASK:
        return
    try:
        args = ChatTurnJobArgs.model_validate(job.task_kwargs)
    except ValidationError:
        logger.warning("Stalled chat turn carries no readable payload", job_id=job.id)
        return
    conversation_id = args.payload.body.conversation_id
    if not await _chat_stream_is_open(conversation_id):
        return
    writer = ChatEventWriter(
        conversation_id=conversation_id,
        turn_id=args.payload.turn_id,
    )
    await close_open_tool_calls(writer, error_text)
    for chunk in (
        ErrorChunk(error_text=error_text),
        turn_failed_event(error_text=error_text),
        FinishChunk(finish_reason="error"),
        DoneChunk(),
    ):
        await writer.write(
            chunk.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
    logger.warning(
        "Closed the stream of a stalled turn",
        job_id=job.id,
        conversation_id=str(conversation_id),
        turn_id=str(args.payload.turn_id),
    )


async def _chat_stream_is_open(conversation_id: UUID) -> bool:
    """True when the newest turn-tagged chunk is not a terminator.

    Rows that belong to no turn, such as task progress in the gap, do not
    speak for the stream.
    """
    async with async_session_factory() as session:
        newest = await session.scalar(
            select(ConversationEvent.chunk["type"].astext)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.task_id.is_(None),
                ConversationEvent.turn_id.is_not(None),
            )
            .order_by(ConversationEvent.id.desc())
            .limit(1),
        )
    return newest is not None and newest != "done"


__all__ = ["release_dead_turn", "release_job", "release_stalled_jobs"]

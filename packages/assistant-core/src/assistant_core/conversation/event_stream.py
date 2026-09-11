from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, Discriminator, Tag, TypeAdapter, ValidationError
from pydantic_ai.ui.vercel_ai.response_types import (
    AbortChunk,
    BaseChunk,
    DataChunk,
    DoneChunk,
    ErrorChunk,
    FileChunk,
    FinishChunk,
    FinishStepChunk,
    MessageMetadataChunk,
    ReasoningDeltaChunk,
    ReasoningEndChunk,
    ReasoningStartChunk,
    SourceDocumentChunk,
    SourceUrlChunk,
    StartChunk,
    StartStepChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolApprovalRequestChunk,
    ToolInputAvailableChunk,
    ToolInputDeltaChunk,
    ToolInputErrorChunk,
    ToolInputStartChunk,
    ToolOutputAvailableChunk,
    ToolOutputDeniedChunk,
    ToolOutputErrorChunk,
)
from sqlalchemy import select
from sqlalchemy.engine import make_url

from assistant_core.conversation.ui_message_reducer import (
    OpenMessageRef,
    open_message_of,
)
from assistant_core.persistence.models import ConversationEvent
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import get_logger
from assistant_core.platform.metrics import SseSubscription, chunk_kind
from assistant_core.platform.pydantic_base import CamelModel

logger = get_logger(__name__)

# A comment frame carries no id and no data, so cursors and the client parser
# see nothing.
_KEEPALIVE_FRAME = ": keep-alive\n\n"


class UserMessage(BaseModel):
    id: str
    role: Literal["user"]
    parts: list[dict[str, Any]]


class SystemMessage(BaseModel):
    id: str
    role: Literal["system"]
    parts: list[dict[str, Any]]


class AssistantMessage(BaseModel):
    id: str
    role: Literal["assistant"]
    parts: list[dict[str, Any]]


class UserMessageChunk(BaseModel):
    type: Literal["user-message"]
    message: UserMessage


class SystemMessageChunk(BaseModel):
    type: Literal["system-message"]
    message: SystemMessage


class AssistantMessageChunk(BaseModel):
    type: Literal["assistant-message"]
    message: AssistantMessage


def _chunk_tag(value: Any) -> str:
    raw_type = value["type"] if isinstance(value, dict) else value.type
    if not isinstance(raw_type, str):
        return ""
    return "data" if raw_type.startswith("data-") else raw_type


_ChunkUnion = Annotated[
    Annotated[TextStartChunk, Tag("text-start")]
    | Annotated[TextDeltaChunk, Tag("text-delta")]
    | Annotated[TextEndChunk, Tag("text-end")]
    | Annotated[ReasoningStartChunk, Tag("reasoning-start")]
    | Annotated[ReasoningDeltaChunk, Tag("reasoning-delta")]
    | Annotated[ReasoningEndChunk, Tag("reasoning-end")]
    | Annotated[ErrorChunk, Tag("error")]
    | Annotated[ToolInputStartChunk, Tag("tool-input-start")]
    | Annotated[ToolInputDeltaChunk, Tag("tool-input-delta")]
    | Annotated[ToolOutputAvailableChunk, Tag("tool-output-available")]
    | Annotated[ToolInputAvailableChunk, Tag("tool-input-available")]
    | Annotated[ToolInputErrorChunk, Tag("tool-input-error")]
    | Annotated[ToolOutputErrorChunk, Tag("tool-output-error")]
    | Annotated[ToolApprovalRequestChunk, Tag("tool-approval-request")]
    | Annotated[ToolOutputDeniedChunk, Tag("tool-output-denied")]
    | Annotated[SourceUrlChunk, Tag("source-url")]
    | Annotated[SourceDocumentChunk, Tag("source-document")]
    | Annotated[FileChunk, Tag("file")]
    | Annotated[DataChunk, Tag("data")]
    | Annotated[StartStepChunk, Tag("start-step")]
    | Annotated[FinishStepChunk, Tag("finish-step")]
    | Annotated[StartChunk, Tag("start")]
    | Annotated[FinishChunk, Tag("finish")]
    | Annotated[AbortChunk, Tag("abort")]
    | Annotated[MessageMetadataChunk, Tag("message-metadata")]
    | Annotated[DoneChunk, Tag("done")]
    | Annotated[UserMessageChunk, Tag("user-message")]
    | Annotated[SystemMessageChunk, Tag("system-message")]
    | Annotated[AssistantMessageChunk, Tag("assistant-message")],
    Discriminator(_chunk_tag),
]

_CHUNK_ADAPTER: TypeAdapter[
    BaseChunk | UserMessageChunk | SystemMessageChunk | AssistantMessageChunk
] = TypeAdapter(_ChunkUnion)


def _asyncpg_dsn(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername.startswith("postgresql+"):
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def _fetch_after(
    conversation_id: UUID,
    after: int,
) -> list[tuple[int, dict[str, Any]]]:
    """Fetch chat-stream chunks. Task-tagged rows belong to the per-task SSE
    endpoint and use a different envelope shape (``{"sse": "<frame>"}``);
    pulling them into the chat replay would crash the v6 chunk discriminator.
    """
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(ConversationEvent)
                .where(
                    ConversationEvent.conversation_id == conversation_id,
                    ConversationEvent.id > after,
                    ConversationEvent.task_id.is_(None),
                )
                .order_by(ConversationEvent.id),
            )
        ).all()
        return [(r.id, r.chunk) for r in rows]


async def fetch_chunks_after(
    conversation_id: UUID,
    after: int,
) -> tuple[int, list[dict[str, Any]]]:
    rows = await _fetch_after(conversation_id, after)
    chunks: list[dict[str, Any]] = []
    cursor = after
    for event_id, chunk in rows:
        cursor = max(cursor, event_id)
        if not isinstance(chunk, dict) or "type" not in chunk:
            continue
        try:
            _CHUNK_ADAPTER.validate_python(chunk)
        except ValidationError:
            continue
        chunks.append(chunk)
    return cursor, chunks


_PROMPT_ENVELOPE_TYPES: tuple[str, ...] = ("user-message", "system-message")


async def latest_snapshot_boundary(conversation_id: UUID) -> int:
    async with async_session_factory() as session:
        last_done = await session.scalar(
            select(ConversationEvent.id)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.task_id.is_(None),
                ConversationEvent.chunk["type"].astext == "done",
            )
            .order_by(ConversationEvent.id.desc())
            .limit(1),
        )
        last_done_id = last_done if last_done is not None else 0
        first_prompt_after_done = await session.scalar(
            select(ConversationEvent.id)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.task_id.is_(None),
                ConversationEvent.id > last_done_id,
                ConversationEvent.chunk["type"].astext.in_(
                    _PROMPT_ENVELOPE_TYPES,
                ),
            )
            .order_by(ConversationEvent.id.asc())
            .limit(1),
        )
        if first_prompt_after_done is not None:
            return first_prompt_after_done
        return last_done_id


class EventsSnapshot(CamelModel):
    """The completed history a thread serves, and where a tail continues it."""

    chunks: list[dict[str, Any]]
    cursor: int
    open_message: OpenMessageRef | None = None


async def fetch_snapshot_chunks(conversation_id: UUID) -> EventsSnapshot:
    boundary = await latest_snapshot_boundary(conversation_id)
    if boundary == 0:
        return EventsSnapshot(chunks=[], cursor=0)
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(ConversationEvent)
                .where(
                    ConversationEvent.conversation_id == conversation_id,
                    ConversationEvent.task_id.is_(None),
                    ConversationEvent.id <= boundary,
                )
                .order_by(ConversationEvent.id),
            )
        ).all()
    entries: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        chunk = row.chunk
        if not isinstance(chunk, dict) or "type" not in chunk:
            continue
        try:
            _CHUNK_ADAPTER.validate_python(chunk)
        except ValidationError:
            continue
        entries.append((row.id, chunk))
    return EventsSnapshot(
        chunks=[chunk for _cursor, chunk in entries],
        cursor=boundary,
        open_message=open_message_of(entries),
    )


async def latest_event(
    conversation_id: UUID,
) -> tuple[int, dict[str, Any]] | None:
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id.desc())
            .limit(1),
        )
        if row is None:
            return None
        return (row.id, row.chunk)


async def latest_turn_boundary(conversation_id: UUID) -> int:
    """Return the id of the most recent turn-terminator (`done` chunk).

    Used as the SSE replay baseline so a new client never tails into the
    middle of a chunk sequence a prior turn is still writing. Task-tagged
    rows are excluded so the boundary tracks the chat stream alone.
    """
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ConversationEvent)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.task_id.is_(None),
                ConversationEvent.chunk["type"].astext == "done",
            )
            .order_by(ConversationEvent.id.desc())
            .limit(1),
        )
        return row.id if row is not None else 0


async def _drain_and_yield(
    conversation_id: UUID,
    last_sent: int,
    queue: asyncio.Queue[int],
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    while True:
        await queue.get()
        while not queue.empty():
            queue.get_nowait()
        for event_id, chunk in await _fetch_after(conversation_id, last_sent):
            yield event_id, chunk
            last_sent = event_id


async def replay_and_tail(
    *,
    conversation_id: UUID,
    after: int,
) -> AsyncGenerator[tuple[int, dict[str, Any]]]:
    last_sent = after
    for event_id, chunk in await _fetch_after(conversation_id, after):
        yield event_id, chunk
        last_sent = event_id

    channel = f"conversation_events:{conversation_id}"
    queue: asyncio.Queue[int] = asyncio.Queue()

    def on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            queue.put_nowait(int(payload))
        except ValueError:
            logger.warning("pg_notify payload not an int", payload=payload)

    dsn = _asyncpg_dsn(get_runtime_settings().database_url)
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.add_listener(channel, on_notify)
        # Sweep after LISTEN arms in case a row landed between the initial
        # SELECT and add_listener.
        for event_id, chunk in await _fetch_after(conversation_id, last_sent):
            yield event_id, chunk
            last_sent = event_id

        async for event_id, chunk in _drain_and_yield(
            conversation_id,
            last_sent,
            queue,
        ):
            yield event_id, chunk
    finally:
        await conn.close()


async def _tail_or_idle(
    source: AsyncGenerator[tuple[int, dict[str, Any]]],
    interval_seconds: float,
) -> AsyncIterator[tuple[int, dict[str, Any]] | None]:
    """Yield each tailed event, and ``None`` after every silent interval.

    The pending pull survives a timeout, so the source generator keeps its
    LISTEN connection across any number of idle intervals.
    """
    pending: asyncio.Task[tuple[int, dict[str, Any]]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(source))
            done, _ = await asyncio.wait({pending}, timeout=interval_seconds)
            if not done:
                yield None
                continue
            finished, pending = pending, None
            try:
                event = finished.result()
            except StopAsyncIteration:
                return
            yield event
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await source.aclose()


async def iter_sse(
    *,
    conversation_id: UUID,
    after: int,
) -> AsyncIterator[str]:
    """Frame this thread's chunks until the turn ends or the reader leaves."""
    subscription = SseSubscription(resumed=after > 0)
    reason = "reader-gone"
    try:
        frames = _frames(conversation_id, after, subscription)
        async with contextlib.aclosing(frames):
            async for frame in frames:
                yield frame
        reason = "turn-end"
    finally:
        subscription.close(reason=reason)


async def _frames(
    conversation_id: UUID,
    after: int,
    subscription: SseSubscription,
) -> AsyncGenerator[str]:
    source = replay_and_tail(conversation_id=conversation_id, after=after)
    interval_seconds = float(get_runtime_settings().sse_keepalive_seconds)
    async for event in _tail_or_idle(source, interval_seconds):
        if event is None:
            subscription.keepalive()
            yield _KEEPALIVE_FRAME
            continue
        event_id, chunk = event
        if not isinstance(chunk, dict) or "type" not in chunk:
            logger.warning(
                "skipping persisted chunk without type discriminator",
                event_id=event_id,
                conversation_id=str(conversation_id),
            )
            continue
        try:
            typed = _CHUNK_ADAPTER.validate_python(chunk)
        except ValidationError:
            logger.warning(
                "skipping unparseable persisted chunk",
                event_id=event_id,
                conversation_id=str(conversation_id),
            )
            continue
        if isinstance(
            typed,
            UserMessageChunk | SystemMessageChunk | AssistantMessageChunk,
        ):
            continue
        subscription.event(chunk_kind(chunk))
        yield _frame_event(event_id, typed)
        if isinstance(typed, DoneChunk):
            return


def _frame_event(event_id: int, chunk: BaseChunk) -> str:
    payload = (
        "[DONE]"
        if isinstance(chunk, DoneChunk)
        else chunk.model_dump_json(by_alias=True, exclude_none=True)
    )
    return f"id: {event_id}\ndata: {payload}\n\n"

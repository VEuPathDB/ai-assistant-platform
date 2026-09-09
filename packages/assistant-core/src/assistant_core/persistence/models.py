"""The tables the runtime reads and writes: threads, turns, chunks, stops,
cost, the scratchpad and the durable tasks.

The declarative base is shared: a host application maps its own tables on it,
so a foreign key between a host table and a runtime table resolves.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator, TypeEngine

from assistant_core.platform.context import DEFAULT_APPLICATION_ID, calling_application

APPLICATION_ID_LENGTH = 64
ASSISTANT_ID_LENGTH = 64
# The assistant a thread takes when its creator names none.
DEFAULT_ASSISTANT_ID = "default"


def application_id_column() -> MappedColumn[str]:
    """The application a row belongs to. Ownership is user plus application.

    An insert that names no application takes the caller's, so a row cannot
    land under an application nobody was acting as.
    """
    return mapped_column(
        String(APPLICATION_ID_LENGTH),
        nullable=False,
        default=calling_application,
        server_default=DEFAULT_APPLICATION_ID,
    )


class GUID(TypeDecorator[UUID]):
    """Platform-independent GUID type.

    The column stores a UUID as CHAR(36). A read returns a UUID object.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[str]:
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(
        self, value: UUID | str | None, dialect: Dialect
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return str(value)
        return value

    def process_result_value(
        self, value: str | UUID | None, dialect: Dialect
    ) -> UUID | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        return UUID(value)


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map: ClassVar[dict[type, type]] = {
        dict: JSON,
        list: JSON,
        UUID: GUID,
    }


class Conversation(Base):
    """One chat thread: who owns it, which assistant answers it, where it runs."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_user_app_site",
            "user_id",
            "application_id",
            "site_id",
        ),
        Index("ix_conversations_assistant_id", "assistant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE")
    )
    application_id: Mapped[str] = application_id_column()
    # The assistant that answers this thread. Set when the thread is created
    # and never changed, so replaying it always runs the same architecture.
    assistant_id: Mapped[str] = mapped_column(
        String(ASSISTANT_ID_LENGTH),
        nullable=False,
        default=DEFAULT_ASSISTANT_ID,
        server_default=DEFAULT_ASSISTANT_ID,
    )
    site_id: Mapped[str] = mapped_column(String(50), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parent_conversation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """Per-turn metadata row that holds usage accounting and trace ids.

    The chunk log in conversation_events is the source of truth for parts.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role",
        ),
        Index(
            "messages_conversation_id_created_at_idx",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    # The attribute has a trailing underscore because DeclarativeBase reserves
    # the name metadata. The column name stays metadata.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ConversationEvent(Base):
    """Durable conversation stream chunk that lets a client resume after a reconnect."""

    __tablename__ = "conversation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("background_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    chunk: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MemoryTombstoneRow(Base):
    """Soft-delete marker that prevents auto-write from re-adding pruned memories."""

    __tablename__ = "memory_tombstones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    application_id: Mapped[str] = application_id_column()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(
        String(32), nullable=False, default="user_deleted"
    )
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "application_id",
            "kind",
            "content_hash",
            name="uq_tombstones_user_app_kind_hash",
        ),
    )


class ChatTurnCancellation(Base):
    """A stop request for one turn, which the worker running it polls."""

    __tablename__ = "chat_turn_cancellations"

    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MonthlyUsage(Base):
    """Accumulated token and cost usage for one application of one user, per month.

    period_start is always the first UTC day of the month. Accumulation is an
    upsert on the user, the application and the period.
    """

    __tablename__ = "monthly_usage"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "application_id",
            "period_start",
            name="monthly_usage_user_app_period_key",
        ),
        Index("monthly_usage_user_idx", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[str] = application_id_column()
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    total_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


_NOTE_FTS = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') "
    "|| setweight(to_tsvector('english', coalesce(summary, '')), 'B') "
    "|| setweight(to_tsvector('english', coalesce(body, '')), 'C')"
)


class ScratchpadNote(Base):
    """One note an agent wrote for itself, scoped to a thread."""

    __tablename__ = "scratchpad_notes"
    __table_args__ = (
        Index(
            "scratchpad_notes_conv_idx",
            "conversation_id",
            text("pinned DESC"),
            text("created_at DESC"),
        ),
        Index(
            "scratchpad_notes_fts_idx",
            "fts",
            postgresql_using="gin",
        ),
        Index(
            "scratchpad_notes_tags_idx",
            "tags",
            postgresql_using="gin",
            postgresql_ops={"tags": "jsonb_path_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    body_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    fts: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(_NOTE_FTS, persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ScratchpadCompaction(Base):
    """What one compaction run started from, ended at and cost."""

    __tablename__ = "scratchpad_compactions"
    __table_args__ = (
        CheckConstraint(
            "trigger_reason IN ('count', 'tokens', 'both')",
            name="ck_scratchpad_compactions_trigger_reason",
        ),
        Index(
            "scratchpad_compactions_conv_idx",
            "conversation_id",
            text("triggered_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    before_count: Mapped[int] = mapped_column(Integer, nullable=False)
    after_count: Mapped[int] = mapped_column(Integer, nullable=False)
    before_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    after_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=6),
        nullable=False,
        server_default="0",
    )
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)


class BackgroundTask(Base):
    """One durable tool call a turn handed to a worker."""

    __tablename__ = "background_tasks"
    __table_args__ = (
        Index("bg_tasks_conversation_idx", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    # The pydantic-ai call this task answers.
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    args: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # The per-role model and reasoning picks the deferring request carried, so
    # the turn that answers this task runs under the same ones.
    phase_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TaskProgressRow(Base):
    """One incremental progress record a durable task emitted."""

    __tablename__ = "task_progress"
    __table_args__ = (Index("task_progress_task_idx", "task_id", "emitted_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("background_tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    percent: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

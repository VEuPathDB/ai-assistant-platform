"""Create the four tables the runtime owns: threads, turns, chunks, tombstones.

Revision ID: 2026_09_09_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from assistant_core.migrate import OWNED_TABLES

revision: str = "2026_09_09_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLICATION_ID_LENGTH = 64
_ASSISTANT_ID_LENGTH = 64
_DEFAULT_APPLICATION_ID = "default"
_DEFAULT_ASSISTANT_ID = "default"


def _existing_tables() -> frozenset[str]:
    inspector = sa.inspect(op.get_bind())
    return frozenset(name for name in OWNED_TABLES if inspector.has_table(name))


def upgrade() -> None:
    # A host whose own chain built all four tables keeps them, and this revision
    # only records that the chain stands at its baseline. A database that holds
    # some of them is a state neither chain produces, so it is refused.
    present = _existing_tables()
    if present == frozenset(OWNED_TABLES):
        return
    if present:
        msg = (
            "the database holds part of the runtime schema: present "
            f"{sorted(present)}, missing {sorted(frozenset(OWNED_TABLES) - present)}"
        )
        raise RuntimeError(msg)
    op.create_table(
        "conversations",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.String(_APPLICATION_ID_LENGTH),
            nullable=False,
            server_default=_DEFAULT_APPLICATION_ID,
        ),
        sa.Column(
            "assistant_id",
            sa.String(_ASSISTANT_ID_LENGTH),
            nullable=False,
            server_default=_DEFAULT_ASSISTANT_ID,
        ),
        sa.Column("site_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parent_conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("parent_message_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversations_user_app_site",
        "conversations",
        ["user_id", "application_id", "site_id"],
    )
    op.create_index("ix_conversations_assistant_id", "conversations", ["assistant_id"])

    op.create_table(
        "messages",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_messages_role"
        ),
    )
    op.create_index(
        "messages_conversation_id_created_at_idx",
        "messages",
        ["conversation_id", "created_at"],
    )
    # The two tables point at each other, so this one closes the cycle.
    op.create_foreign_key(
        None,
        "conversations",
        "messages",
        ["parent_message_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "conversation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("turn_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("chunk", JSONB, nullable=False),
        sa.Column(
            "emitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversation_events_conversation_id",
        "conversation_events",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_events_task_id", "conversation_events", ["task_id"]
    )

    op.create_table(
        "memory_tombstones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.String(_APPLICATION_ID_LENGTH),
            nullable=False,
            server_default=_DEFAULT_APPLICATION_ID,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "application_id",
            "kind",
            "content_hash",
            name="uq_tombstones_user_app_kind_hash",
        ),
    )
    op.create_index("ix_memory_tombstones_user_id", "memory_tombstones", ["user_id"])


def downgrade() -> None:
    msg = (
        "the baseline does not drop the runtime tables: a database stamped at it "
        "may hold tables a host chain built"
    )
    raise NotImplementedError(msg)

"""Create the durable-task tables the runtime owns.

Revision ID: 2026_09_09_0004
Revises: 2026_09_09_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "2026_09_09_0004"
down_revision: str | Sequence[str] | None = "2026_09_09_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables this revision creates. A revision is history: the set stays as it
# was when the revision was written, while OWNED_TABLES grows with the chain.
CREATES = (
    "background_tasks",
    "task_progress",
)


# The key the baseline could not write, named so this revision can find it.
TASK_KEY = "conversation_events_task_id_fkey"


def _existing_tables() -> frozenset[str]:
    inspector = sa.inspect(op.get_bind())
    return frozenset(name for name in CREATES if inspector.has_table(name))


def _task_key_is_present() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        key["constrained_columns"] == ["task_id"]
        for key in inspector.get_foreign_keys("conversation_events")
    )


def upgrade() -> None:
    # A host whose own chain built both tables keeps them. A half-built
    # database is refused rather than stamped over.
    present = _existing_tables()
    if present and present != frozenset(CREATES):
        msg = (
            "the database holds part of the runtime schema: present "
            f"{sorted(present)}, missing {sorted(frozenset(CREATES) - present)}"
        )
        raise RuntimeError(msg)
    if not present:
        _create_task_tables()
    # The baseline leaves this key to this revision, whichever chain created
    # the table it points at.
    if not _task_key_is_present():
        op.create_foreign_key(
            TASK_KEY,
            "conversation_events",
            "background_tasks",
            ["task_id"],
            ["id"],
            ondelete="CASCADE",
        )


def _create_task_tables() -> None:
    op.create_table(
        "background_tasks",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("args", JSONB(), nullable=False, server_default="{}"),
        sa.Column("phase_overrides", JSONB(), nullable=False, server_default="{}"),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "estimated_duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_background_tasks_conversation_id",
        "background_tasks",
        ["conversation_id"],
    )
    op.create_index("ix_background_tasks_user_id", "background_tasks", ["user_id"])
    op.create_index(
        "bg_tasks_conversation_idx",
        "background_tasks",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "task_progress",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column(
            "task_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("percent", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", JSONB(), nullable=True),
        sa.Column(
            "emitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_task_progress_task_id", "task_progress", ["task_id"])
    op.create_index(
        "task_progress_task_idx",
        "task_progress",
        ["task_id", "emitted_at"],
    )


def downgrade() -> None:
    msg = (
        "this revision does not drop the runtime tables: a database stamped at it "
        "may hold tables a host chain built"
    )
    raise NotImplementedError(msg)

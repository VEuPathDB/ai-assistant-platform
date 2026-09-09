"""Create the scratchpad tables the runtime owns.

Revision ID: 2026_09_09_0003
Revises: 2026_09_09_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "2026_09_09_0003"
down_revision: str | Sequence[str] | None = "2026_09_09_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables this revision creates. A revision is history: the set stays as it
# was when the revision was written, while OWNED_TABLES grows with the chain.
CREATES = (
    "scratchpad_notes",
    "scratchpad_compactions",
)

_FTS = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') "
    "|| setweight(to_tsvector('english', coalesce(summary, '')), 'B') "
    "|| setweight(to_tsvector('english', coalesce(body, '')), 'C')"
)


def _existing_tables() -> frozenset[str]:
    inspector = sa.inspect(op.get_bind())
    return frozenset(name for name in CREATES if inspector.has_table(name))


def upgrade() -> None:
    # A host whose own chain built both tables keeps them. A half-built
    # database is refused rather than stamped over.
    present = _existing_tables()
    if present == frozenset(CREATES):
        return
    if present:
        msg = (
            "the database holds part of the runtime schema: present "
            f"{sorted(present)}, missing {sorted(frozenset(CREATES) - present)}"
        )
        raise RuntimeError(msg)

    op.create_table(
        "scratchpad_notes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("body_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "fts",
            TSVECTOR(),
            sa.Computed(_FTS, persisted=True),
            nullable=False,
        ),
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
        "scratchpad_notes_conv_idx",
        "scratchpad_notes",
        ["conversation_id", sa.text("pinned DESC"), sa.text("created_at DESC")],
    )
    op.create_index(
        "scratchpad_notes_fts_idx",
        "scratchpad_notes",
        ["fts"],
        postgresql_using="gin",
    )
    op.create_index(
        "scratchpad_notes_tags_idx",
        "scratchpad_notes",
        ["tags"],
        postgresql_using="gin",
        postgresql_ops={"tags": "jsonb_path_ops"},
    )

    op.create_table(
        "scratchpad_compactions",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column(
            "conversation_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("before_count", sa.Integer(), nullable=False),
        sa.Column("after_count", sa.Integer(), nullable=False),
        sa.Column("before_tokens", sa.Integer(), nullable=False),
        sa.Column("after_tokens", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "trigger_reason IN ('count', 'tokens', 'both')",
            name="ck_scratchpad_compactions_trigger_reason",
        ),
    )
    op.create_index(
        "scratchpad_compactions_conv_idx",
        "scratchpad_compactions",
        ["conversation_id", sa.text("triggered_at DESC")],
    )


def downgrade() -> None:
    msg = (
        "this revision does not drop the runtime tables: a database stamped at it "
        "may hold tables a host chain built"
    )
    raise NotImplementedError(msg)

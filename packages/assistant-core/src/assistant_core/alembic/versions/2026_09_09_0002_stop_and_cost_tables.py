"""Create the stop-request and monthly-cost tables the runtime owns.

Revision ID: 2026_09_09_0002
Revises: 2026_09_09_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "2026_09_09_0002"
down_revision: str | Sequence[str] | None = "2026_09_09_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLICATION_ID_LENGTH = 64
_DEFAULT_APPLICATION_ID = "default"

# The tables this revision creates. A revision is history: the set stays as it
# was when the revision was written, while OWNED_TABLES grows with the chain.
CREATES = (
    "chat_turn_cancellations",
    "monthly_usage",
)


def _existing_tables() -> frozenset[str]:
    inspector = sa.inspect(op.get_bind())
    return frozenset(name for name in CREATES if inspector.has_table(name))


def upgrade() -> None:
    # A host whose own chain built both tables keeps them, the way the baseline
    # keeps the four it would otherwise create. A half-built database is refused.
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
        "chat_turn_cancellations",
        sa.Column("conversation_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("turn_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            "turn_id",
            name="pk_chat_turn_cancellations",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "monthly_usage",
        sa.Column("id", sa.CHAR(36), primary_key=True),
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
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "total_cost_usd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "application_id",
            "period_start",
            name="monthly_usage_user_app_period_key",
        ),
    )
    op.create_index("monthly_usage_user_idx", "monthly_usage", ["user_id"])


def downgrade() -> None:
    msg = (
        "this revision does not drop the runtime tables: a database stamped at it "
        "may hold tables a host chain built"
    )
    raise NotImplementedError(msg)

"""Record who paid for every monthly usage row.

Revision ID: 2026_09_24_0005
Revises: 2026_09_09_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_24_0005"
down_revision: str | Sequence[str] | None = "2026_09_09_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables this revision creates. A revision is history: the set stays as it
# was when the revision was written, while OWNED_TABLES grows with the chain.
CREATES: tuple[str, ...] = ()

_PAID_BY_LENGTH = 16
_KEY = "monthly_usage_user_app_period_payer_key"
_CHECK = "ck_monthly_usage_paid_by"
_PAYERLESS_KEY = ["user_id", "application_id", "period_start"]


def _payer_is_present() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column["name"] == "paid_by" for column in inspector.get_columns("monthly_usage")
    )


def _payerless_key_names() -> list[str]:
    inspector = sa.inspect(op.get_bind())
    return [
        str(key["name"])
        for key in inspector.get_unique_constraints("monthly_usage")
        if key["column_names"] == _PAYERLESS_KEY
    ]


def upgrade() -> None:
    # A host whose own chain built the table from the current models has the
    # column already, and keeps it.
    if _payer_is_present():
        return
    # Every row written before this revision was spent on the deployment's key.
    op.add_column(
        "monthly_usage",
        sa.Column(
            "paid_by",
            sa.String(_PAID_BY_LENGTH),
            nullable=False,
            server_default="deployment",
        ),
    )
    # A writer from now on names the payer itself.
    op.alter_column("monthly_usage", "paid_by", server_default=None)
    op.create_check_constraint(
        _CHECK, "monthly_usage", "paid_by IN ('deployment', 'user')"
    )
    for name in _payerless_key_names():
        op.drop_constraint(name, "monthly_usage", type_="unique")
    op.create_unique_constraint(
        _KEY,
        "monthly_usage",
        [*_PAYERLESS_KEY, "paid_by"],
    )


def downgrade() -> None:
    msg = (
        "this revision does not drop the payer: two rows of one period that differ "
        "only in who paid would merge into one"
    )
    raise NotImplementedError(msg)

"""Drop the history deltas a turn logged before the stream left them out.

Revision ID: 2026_11_07_0006
Revises: 2026_09_24_0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2026_11_07_0006"
down_revision: str | Sequence[str] | None = "2026_09_24_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATES: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "DELETE FROM conversation_events WHERE chunk->>'type' IN ("
        "'data-model-settings-delta', "
        "'data-tool-availability-delta', "
        "'data-capability-load-delta')"
    )


def downgrade() -> None:
    pass

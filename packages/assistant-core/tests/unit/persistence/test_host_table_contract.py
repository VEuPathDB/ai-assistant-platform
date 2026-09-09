"""The host-table contract the runtime declares, checked against the models."""

from tests._host_schema import HOST_USERS

from assistant_core.migrate import OWNED_TABLES
from assistant_core.persistence.models import Base

# What one runtime table names in another.
RUNTIME_REFERENCES = {"conversations.id", "messages.id", "background_tasks.id"}

# What a host supplies.
HOST_CONTRACT = {"users.id"}


def test_the_runtime_reaches_only_the_documented_host_columns() -> None:
    reached = {
        key.target_fullname
        for name in OWNED_TABLES
        for key in Base.metadata.tables[name].foreign_keys
    }

    assert reached == RUNTIME_REFERENCES | HOST_CONTRACT


def test_the_suite_fabricates_the_contract_and_nothing_more() -> None:
    """Every other suite runs against this one table, so a pass is the proof."""
    fabricated = {f"{HOST_USERS.name}.{column.name}" for column in HOST_USERS.columns}

    assert fabricated == HOST_CONTRACT

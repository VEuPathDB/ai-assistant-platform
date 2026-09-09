"""The host-table contract the runtime declares, checked against the models."""

from tests._host_schema import HOST_BACKGROUND_TASKS, HOST_USERS

from assistant_core.migrate import OWNED_TABLES
from assistant_core.persistence.models import Base

# What one runtime table names in another.
RUNTIME_REFERENCES = {"conversations.id", "messages.id"}

# What a host supplies. `users` is the host's for good; `background_tasks`
# stays the host's until the runtime ships it with the task subsystem.
HOST_CONTRACT = {"users.id", "background_tasks.id"}


def test_the_runtime_reaches_only_the_documented_host_columns() -> None:
    reached = {
        key.target_fullname
        for name in OWNED_TABLES
        for key in Base.metadata.tables[name].foreign_keys
    }

    assert reached == RUNTIME_REFERENCES | HOST_CONTRACT


def test_the_suite_fabricates_the_contract_and_nothing_more() -> None:
    """Every other suite runs against these two tables, so a pass is the proof."""
    fabricated = {
        f"{table.name}.{column.name}"
        for table in (HOST_USERS, HOST_BACKGROUND_TASKS)
        for column in table.columns
    }

    assert fabricated == HOST_CONTRACT

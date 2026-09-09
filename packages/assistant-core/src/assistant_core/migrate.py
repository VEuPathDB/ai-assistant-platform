"""Bring the runtime's tables to this distribution's head."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

# This distribution's chain shares a database with its host's. Each records its
# position in a version table of its own.
VERSION_TABLE = "alembic_version_assistant_core"

# The tables this distribution creates and migrates. A host owns every other
# table in the database.
OWNED_TABLES = (
    "conversations",
    "messages",
    "conversation_events",
    "memory_tombstones",
    "chat_turn_cancellations",
    "monthly_usage",
    "scratchpad_notes",
    "scratchpad_compactions",
    "background_tasks",
    "task_progress",
)


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: object,
    compare_to: object,
) -> bool:
    """Keep the tables this distribution owns, so autogenerate ignores a host's."""
    if type_ != "table":
        return True
    return name in OWNED_TABLES


def alembic_config() -> Config:
    """The chain that ships with this package."""
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "alembic")
    )
    return config


def upgrade_head(connection: Connection) -> None:
    """Run the chain on a connection the host already opened."""
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def main() -> None:
    """Run the chain on the database ``RuntimeSettings`` names."""
    command.upgrade(alembic_config(), "head")


if __name__ == "__main__":
    main()

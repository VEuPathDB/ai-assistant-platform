"""The host tables the runtime points at but does not own.

The contract is one column per table: a ``users`` row the runtime attributes a
thread to, and until the task subsystem moves, a ``background_tasks`` row a
chunk belongs to. See docs/knowledge/decisions/the-runtime-owns-its-task-tables.md.
"""

from sqlalchemy import Column, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from assistant_core.persistence.models import GUID, Base

HOST_USERS = Table("users", Base.metadata, Column("id", GUID(), primary_key=True))

HOST_BACKGROUND_TASKS = Table(
    "background_tasks",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
)

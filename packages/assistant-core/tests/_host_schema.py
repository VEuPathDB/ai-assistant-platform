"""The host tables the runtime points at but does not own.

A runtime table names ``users`` and ``background_tasks`` in a foreign key, so
a database the runtime stands up alone still needs them to exist.
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

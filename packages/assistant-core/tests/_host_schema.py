"""The host table the runtime points at but does not own.

The contract is one column: a ``users`` row the runtime attributes a thread
and a durable task to.
See docs/knowledge/decisions/the-runtime-owns-its-task-tables.md.
"""

from sqlalchemy import Column, Table

from assistant_core.persistence.models import GUID, Base

HOST_USERS = Table("users", Base.metadata, Column("id", GUID(), primary_key=True))

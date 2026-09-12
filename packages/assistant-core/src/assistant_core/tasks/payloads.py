"""The kwargs a durable job carries from the deferring turn to the worker.

Procrastinate stores task kwargs as JSON, so the payload is dumped at the
dispatch and validated at the worker entry point.
"""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from assistant_core.models.capture import current_capture_dir
from assistant_core.platform.types import JSONObject
from assistant_core.tasks.job_context import DurableJobState, durable_job_context


class DurableTaskPayload(BaseModel):
    """Typed payload for a ``durable:<tool_name>`` procrastinate job."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    task_id: UUID
    thread_id: UUID
    args: JSONObject = Field(default_factory=dict)
    capture_dir: str | None = None
    # What the host captured at the call, restored around the body. The host's
    # own subclass serialises itself, so its fields reach the worker.
    job_context: SerializeAsAny[DurableJobState] = Field(
        default_factory=DurableJobState,
    )

    @classmethod
    def from_context(
        cls,
        *,
        task_id: UUID,
        thread_id: UUID,
        args: JSONObject,
    ) -> Self:
        """Build a payload, capturing the host's state and the capture run dir."""
        return cls(
            task_id=task_id,
            thread_id=thread_id,
            args=args,
            capture_dir=current_capture_dir(),
            job_context=durable_job_context().capture(),
        )


class StalledDurableTask(BaseModel):
    """A durable job's payload as the stalled-job sweep reads it back.

    The carried state stays JSON here, because the host's own state type is
    the only model that validates it without dropping its fields.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: UUID
    thread_id: UUID
    job_context: JSONObject = Field(default_factory=dict)


__all__ = ["DurableTaskPayload", "StalledDurableTask"]

"""Payloads of the durable-task parts: started, progress, completed."""

from __future__ import annotations

from typing import Any, Literal

from assistant_core.platform.pydantic_base import CamelModel


class BackgroundTaskStarted(CamelModel):
    task_id: str
    tool_name: str
    estimated_duration_seconds: int


class TaskProgress(CamelModel):
    task_id: str
    percent: float
    message: str
    tool_specific: dict[str, Any] | None = None


class TaskCompleted(CamelModel):
    task_id: str
    status: Literal["success", "failed"]
    error: str | None = None
